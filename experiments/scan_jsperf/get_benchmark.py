"""jsperf.app ベンチマーク HTML からコード構成要素を抽出する．

``outputs/scan_jsperf/index.json`` で ``status=fetched`` のエントリを巡回し，
保存済み HTML から Next.js の SSR ペイロードに含まれる以下の情報を抽出する．

- ``title`` (``h1[itemProp=name]`` のテキスト)
- ``description_html`` / ``description_text``
  (``div[itemProp=description]`` の innerHTML と，そのプレーンテキスト)
- ``preparation_html`` (``initHTML``)
- ``setup`` / ``teardown`` (各スクリプト)
- ``tests`` (``title``/``code``/``async`` を持つテストコード列)

抽出結果は ``outputs/scan_jsperf/benchmarks.json`` に **全ベンチマークを 1
ファイルにまとめて** 保存する．各エントリには ``index.json`` の identity
(``slug``/``revision``/``year``/``url``/``lastmod``) を埋め込み，単独で出自
を辿れるようにする．抽出失敗は ``outputs/scan_jsperf/extraction_errors.jsonl``
に書き出す．

CLI:
    ``--workers N`` で並列ワーカー数を指定．``1`` で逐次（デフォルト），``0``
    で ``os.cpu_count()`` を採用．
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hayalab.config import PathConfig

_JS_STRING_START_RE = re.compile(r"""self\.__next_f\.push\(\s*\[\s*1\s*,\s*(['"])""")
_PAYLOAD_PREFIX_RE = re.compile(r"^[0-9a-fA-F]+:")
_BENCHMARK_KEYS = frozenset({"initHTML", "setup", "teardown", "tests"})
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _now_utc_iso() -> str:
    """現在時刻 (UTC) を ISO 8601 文字列で返す．

    Returns:
        ``YYYY-MM-DDTHH:MM:SSZ`` 形式の文字列．
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iter_js_string_bodies(html_text: str) -> list[str]:
    r"""``self.__next_f.push([1, '...' or "..."])`` の JS 文字列本体を順に取り出す．

    jsperf.app は HTML 形式によりシングルクォート版（pretty-printed）と
    ダブルクォート版（minified）の両方を返すため，どちらにも対応する．
    正規表現での一括マッチはバックトラッキングが爆発するため，開始位置と
    クォート種別のみ正規表現で検出し，終端は手動で（``\\`` のエスケープを
    考慮しつつ）走査する．

    Args:
        html_text: HTML 全文．

    Returns:
        JS 文字列本体（未エスケープ）のリスト．
    """
    bodies: list[str] = []
    n = len(html_text)
    for m in _JS_STRING_START_RE.finditer(html_text):
        quote = m.group(1)
        i = m.end()
        while i < n:
            c = html_text[i]
            if c == "\\":
                i += 2
                continue
            if c == quote:
                break
            i += 1
        bodies.append(html_text[m.end() : i])
    return bodies


def _js_unescape(s: str) -> str:
    r"""JavaScript 文字列リテラルのエスケープを解決する．

    対応するエスケープ: ``\\``, ``\'``, ``\"``, ``\n``, ``\t``, ``\r``,
    ``\b``, ``\f``, ``\/``, ``\0``, ``\xHH``, ``\uHHHH``．未知のエスケープは
    次の 1 文字をそのまま採用する．

    Args:
        s: JS 文字列内の生テキスト．

    Returns:
        エスケープを解決した文字列．
    """
    simple = {
        "\\": "\\",
        "'": "'",
        '"': '"',
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "b": "\b",
        "f": "\f",
        "/": "/",
        "0": "\0",
    }
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "u":
                out.append(chr(int(s[i + 2 : i + 6], 16)))
                i += 6
                continue
            if nxt == "x":
                out.append(chr(int(s[i + 2 : i + 4], 16)))
                i += 4
                continue
            out.append(simple.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _iter_ssr_trees(html_text: str) -> list[Any]:
    """SSR ペイロード文字列を JSON ツリーとして列挙する．

    ``"initHTML"`` を含む文字列のみ対象とすれば十分だが，title/description
    は別のペイロードチャンクに入ることもあるため，パース可能なものを全て
    返す．

    Args:
        html_text: HTML 全文．

    Returns:
        各 SSR チャンクをパースした JSON ツリーのリスト．パース不能なものは
        除外する．
    """
    trees: list[Any] = []
    for raw in _iter_js_string_bodies(html_text):
        decoded = _js_unescape(raw)
        payload = _PAYLOAD_PREFIX_RE.sub("", decoded, count=1).rstrip()
        try:
            trees.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return trees


def _find_first(node: Any, predicate: Callable[[Any], bool]) -> Any | None:
    """``predicate(node)`` を満たす最初のノードを再帰探索で返す．

    Args:
        node: 探索開始ノード（dict/list/原子値のいずれか）．
        predicate: 真偽を返す述語関数．

    Returns:
        最初にマッチしたノード．見つからなければ ``None``．
    """
    if predicate(node):
        return node
    if isinstance(node, dict):
        for v in node.values():
            found = _find_first(v, predicate)
            if found is not None:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_first(v, predicate)
            if found is not None:
                return found
    return None


def _find_benchmark_node(tree: Any) -> dict[str, Any] | None:
    """``initHTML``/``setup``/``teardown``/``tests`` を全て持つ辞書を返す．

    Args:
        tree: SSR ツリー．

    Returns:
        該当ノード．見つからなければ ``None``．
    """
    return _find_first(
        tree,
        lambda n: isinstance(n, dict) and _BENCHMARK_KEYS.issubset(n.keys()),
    )


def _find_title(tree: Any) -> str | None:
    """``h1[itemProp=name]`` の最初のテキスト children を返す．

    React SSR の表現は ``["$", "h1", null, {"itemProp": "name",
    "children": ["Get Property Access Times", ["$", ...]]}]`` 形式．

    Args:
        tree: SSR ツリー．

    Returns:
        タイトル文字列．見つからなければ ``None``．
    """

    def is_title_props(n: Any) -> bool:
        return isinstance(n, dict) and n.get("itemProp") == "name"

    props = _find_first(tree, is_title_props)
    if not isinstance(props, dict):
        return None
    children = props.get("children")
    if isinstance(children, str):
        return children
    if isinstance(children, list):
        for c in children:
            if isinstance(c, str):
                return c
    return None


def _find_description_html(tree: Any) -> str | None:
    """``div[itemProp=description]`` の ``__html`` を返す．

    Args:
        tree: SSR ツリー．

    Returns:
        description の innerHTML．無ければ ``None``．
    """

    def is_desc_props(n: Any) -> bool:
        return isinstance(n, dict) and n.get("itemProp") == "description"

    props = _find_first(tree, is_desc_props)
    if not isinstance(props, dict):
        return None
    dh = props.get("dangerouslySetInnerHTML")
    if isinstance(dh, dict):
        html = dh.get("__html")
        if isinstance(html, str):
            return html
    return None


def _strip_html(html: str) -> str:
    """HTML タグを除去し空白を正規化したプレーンテキストを返す．

    Args:
        html: HTML 断片．

    Returns:
        タグ除去・主要エンティティデコード・連続空白圧縮後の文字列．
    """
    text = _TAG_RE.sub("", html)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return _WS_RE.sub(" ", text).strip()


def extract_benchmark(html_text: str) -> dict[str, Any]:
    """HTML テキストからベンチマーク構成要素を抽出する．

    Args:
        html_text: jsperf.app ベンチマークページの HTML 全文．

    Returns:
        次のキーを持つ辞書．

        - ``title`` (str): ベンチマーク名（取得失敗時は空文字列）
        - ``description_html`` (str): 説明文の原 HTML（無ければ空文字列）
        - ``description_text`` (str): タグ除去後のプレーンテキスト
        - ``preparation_html`` (str): Preparation HTML
        - ``setup`` (str): Setup スクリプト
        - ``teardown`` (str): Teardown スクリプト
        - ``tests`` (list[dict]): 各テストコード（``title``/``code``/``async``）

    Raises:
        ValueError: ``initHTML``/``setup``/``teardown``/``tests`` を含む
            ペイロードが HTML 内に存在しない場合．
    """
    trees = _iter_ssr_trees(html_text)

    bench: dict[str, Any] | None = None
    title: str | None = None
    desc_html: str | None = None
    for tree in trees:
        if bench is None:
            bench = _find_benchmark_node(tree)
        if title is None:
            title = _find_title(tree)
        if desc_html is None:
            desc_html = _find_description_html(tree)
        if bench is not None and title is not None and desc_html is not None:
            break

    if bench is None:
        raise ValueError("ベンチマーク構成要素を含む Next.js ペイロードが HTML 内に見つかりませんでした．")

    description_html = desc_html or ""
    return {
        "title": title or "",
        "description_html": description_html,
        "description_text": _strip_html(description_html) if description_html else "",
        "preparation_html": bench.get("initHTML", ""),
        "setup": bench.get("setup", ""),
        "teardown": bench.get("teardown", ""),
        "tests": bench.get("tests", []),
    }


def _extract_entry(
    task: tuple[dict[str, Any], Path],
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """per-entry ワーカー（HTML 読み込み + 抽出）．並列実行から呼ばれる．

    ``ProcessPoolExecutor`` から呼べるよう副作用を持たず，結果をタプルで
    返すだけにする．

    Args:
        task: ``(entry, html_path)`` のタプル．``entry`` は ``index.json`` の
            単一エントリ，``html_path`` は対応する HTML の絶対パス．

    Returns:
        ``(entry, extracted_or_None, error_message_or_None)``．抽出に成功した
        場合は ``extracted`` が辞書，失敗時は ``error_message`` が文字列．
    """
    entry, html_path = task
    if not html_path.is_file():
        return entry, None, f"HTML が存在しません: {html_path}"
    try:
        html_text = html_path.read_text(encoding="utf-8")
        extracted = extract_benchmark(html_text)
    except ValueError as exc:
        return entry, None, str(exc)
    except Exception as exc:  # noqa: BLE001 - 並列実行中の予期しないエラーも記録
        return entry, None, f"{type(exc).__name__}: {exc}"
    return entry, extracted, None


if __name__ == "__main__":
    # --- CLI 引数 -------------------------------------------------------------
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="並列ワーカー数（1=逐次，0=os.cpu_count()，N>=2=N プロセス並列）．デフォルト 1．",
    )
    cli_args = parser.parse_args()
    workers = cli_args.workers if cli_args.workers != 0 else (os.cpu_count() or 1)

    # --- パス決定 ------------------------------------------------------------
    path_config = PathConfig()
    base_dir = path_config.outputs / "scan_jsperf"
    index_path = base_dir / "index.json"
    benchmarks_path = base_dir / "benchmarks.json"
    error_log_path = base_dir / "extraction_errors.jsonl"

    # --- index.json の存在チェック -------------------------------------------
    if not index_path.is_file():
        print(f"index.json が見つかりません: {index_path}")
        print("先に get_html.py を実行してください．")
        raise SystemExit(1)

    # --- 抽出対象（status=fetched）の列挙＆順序固定 --------------------------
    index = json.loads(index_path.read_text(encoding="utf-8"))
    entries = index.get("entries", [])
    targets = [e for e in entries if e["status"] == "fetched"]
    targets.sort(key=lambda e: (-e["year"], e["slug"], e["revision"]))
    tasks: list[tuple[dict[str, Any], Path]] = [(e, base_dir / e["html_path"]) for e in targets]
    print(f"抽出対象: {len(tasks)} / {len(entries)} (workers={workers})")

    # --- 並列／逐次で抽出 ---------------------------------------------------
    results: list[tuple[dict[str, Any], dict[str, Any] | None, str | None]] = []
    if workers <= 1:
        for i, task in enumerate(tasks, 1):
            results.append(_extract_entry(task))
            if i % 200 == 0 or i == len(tasks):
                print(f"  進捗: {i}/{len(tasks)}")
    else:
        chunksize = max(1, len(tasks) // (workers * 16))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for i, result in enumerate(pool.map(_extract_entry, tasks, chunksize=chunksize), 1):
                results.append(result)
                if i % 200 == 0 or i == len(tasks):
                    print(f"  進捗: {i}/{len(tasks)}")

    # --- 成功／失敗を仕分け --------------------------------------------------
    benchmarks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for entry, extracted, error in results:
        if error is not None or extracted is None:
            errors.append(
                {
                    "url": entry["url"],
                    "slug": entry["slug"],
                    "revision": entry["revision"],
                    "year": entry["year"],
                    "source_html": entry["html_path"],
                    "error": error or "unknown",
                }
            )
            continue
        benchmarks.append(
            {
                "slug": entry["slug"],
                "revision": entry["revision"],
                "year": entry["year"],
                "url": entry["url"],
                "lastmod": entry["lastmod"],
                "title": extracted["title"],
                "description_text": extracted["description_text"],
                "description_html": extracted["description_html"],
                "preparation_html": extracted["preparation_html"],
                "setup": extracted["setup"],
                "teardown": extracted["teardown"],
                "tests": extracted["tests"],
                "source_html": entry["html_path"],
            }
        )

    # --- 単一 JSON に書き出し ------------------------------------------------
    benchmarks_payload = {
        "generated_at": _now_utc_iso(),
        "source_index": "index.json",
        "summary": {
            "total_targets": len(tasks),
            "extracted": len(benchmarks),
            "failed": len(errors),
        },
        "benchmarks": benchmarks,
    }
    benchmarks_path.parent.mkdir(parents=True, exist_ok=True)
    benchmarks_path.write_text(
        json.dumps(benchmarks_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- エラーログ（失敗があれば JSONL に上書き保存） ----------------------
    if errors:
        ts = _now_utc_iso()
        error_log_path.parent.mkdir(parents=True, exist_ok=True)
        with error_log_path.open("w", encoding="utf-8") as f:
            for err in errors:
                f.write(json.dumps({"logged_at": ts, **err}, ensure_ascii=False) + "\n")

    # --- 完了サマリ ----------------------------------------------------------
    print(f"完了: 抽出={len(benchmarks)} 失敗={len(errors)} -> {benchmarks_path.name}")
    if errors:
        print(f"  エラーログ: {error_log_path}")
