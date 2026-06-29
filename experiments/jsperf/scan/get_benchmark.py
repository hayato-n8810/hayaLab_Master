"""jsperf.app ベンチマーク HTML から構成要素を抽出して JSON にまとめる．

``index.json`` の ``status=fetched`` を巡回し，``<h1 itemprop=name>`` と
``<*itemprop=description>`` を BeautifulSoup で，JSON-LD ブロック本体を
``json.JSONDecoder.raw_decode`` で取り出して
``outputs/scan_jsperf/benchmarks.json`` に書き出す．

CLI: ``--workers N``  (``1`` で逐次，``0`` で ``os.cpu_count()``)．
"""

from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from hayalab.config import PathConfig

_LD_START_RE = re.compile(
    r"""<script\b[^>]*\btype\s*=\s*["']application/ld\+json["'][^>]*>\s*""",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")

_SUFFIX_PREPARATION = " Javascript Benchmark HTML Setup"
_SUFFIX_SETUP = " Javascript Benchmark Setup Script"


def _now_utc_iso() -> str:
    """現在時刻 (UTC) を ISO 8601 文字列で返す．

    Returns:
        ``YYYY-MM-DDTHH:MM:SSZ`` 形式の文字列．
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _code_after_heading(soup: BeautifulSoup, heading: str) -> str:
    """``<h2>heading</h2>`` 直後の ``<pre><code>`` のプレーンテキストを返す．

    Args:
        soup: ページの BeautifulSoup ツリー．
        heading: ``<h2>`` のテキスト（例: ``"Preparation HTML"``）．

    Returns:
        ``<code>`` の中身（``<span>`` 剥がし & HTML エンティティ復号済み）．
        見つからなければ空文字列．
    """
    h2 = soup.find("h2", string=heading)
    if h2 is None:
        return ""
    pre = h2.find_next_sibling("pre")
    if pre is None:
        return ""
    code = pre.find("code")
    return code.get_text() if code is not None else ""


def extract_benchmark(html_text: str) -> dict[str, Any]:
    """HTML テキストからベンチマーク構成要素を抽出する．

    Args:
        html_text: jsperf.app ベンチマークページの HTML 全文．

    Returns:
        ``title`` / ``description_text`` /
        ``preparation_html`` / ``setup`` / ``teardown`` / ``tests`` をキーに
        持つ辞書．``tests`` は ``title`` と ``code`` を持つ辞書のリスト．

    Raises:
        ValueError: ``SoftwareSourceCode`` テストエントリが 0 件の場合．
    """
    soup = BeautifulSoup(html_text, "lxml")

    h1 = soup.find("h1", attrs={"itemprop": "name"})
    title = h1.get_text(strip=True) if h1 is not None else ""

    desc_el = soup.find(attrs={"itemprop": "description"})
    if desc_el is not None:
        description_text = _WS_RE.sub(" ", desc_el.get_text(" ", strip=True)).strip()
    else:
        description_text = ""

    preparation_html = _code_after_heading(soup, "Preparation HTML")
    setup = _code_after_heading(soup, "Setup")
    teardown = _code_after_heading(soup, "Teardown")

    decoder = json.JSONDecoder()
    tests: list[dict[str, Any]] = []
    for m in _LD_START_RE.finditer(html_text):
        try:
            block, _ = decoder.raw_decode(html_text, m.end())
        except json.JSONDecodeError:
            continue
        if not isinstance(block, dict) or block.get("@type") != "SoftwareSourceCode":
            continue
        name = block.get("name", "")
        text = block.get("text", "")
        if not isinstance(name, str) or not isinstance(text, str):
            continue
        if name.endswith(_SUFFIX_PREPARATION) or name.endswith(_SUFFIX_SETUP):
            continue
        tests.append({"title": name, "code": text})

    if not tests:
        raise ValueError("JSON-LD ブロックから SoftwareSourceCode のテストエントリを抽出できませんでした．")

    return {
        "title": title,
        "description_text": description_text,
        "preparation_html": preparation_html,
        "setup": setup,
        "teardown": teardown,
        "tests": tests,
    }


def _extract_entry(
    task: tuple[dict[str, Any], Path],
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """1 エントリの HTML を読んで抽出する．

    Args:
        task: ``(entry, html_path)`` のタプル．

    Returns:
        ``(entry, extracted_or_None, error_message_or_None)``．
    """
    entry, html_path = task
    if not html_path.is_file():
        return entry, None, f"HTML が存在しません: {html_path}"
    try:
        html_text = html_path.read_text(encoding="utf-8")
        extracted = extract_benchmark(html_text)
    except ValueError as exc:
        return entry, None, str(exc)
    except Exception as exc:  # noqa: BLE001
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
    out_dir = path_config.outputs / "jsperf" / "scan"
    index_path = out_dir / "index.json"
    benchmarks_path = out_dir / "benchmarks.json"
    error_log_path = out_dir / "extraction_errors.jsonl"

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
    tasks: list[tuple[dict[str, Any], Path]] = [(e, out_dir / e["html_path"]) for e in targets]
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
        "source_index": "../index.json",
        "extractor": "get_benchmark_v3 (BeautifulSoup + raw_decode hybrid)",
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

    # --- エラーログ ----------------------------------------------------------
    if errors:
        ts = _now_utc_iso()
        error_log_path.parent.mkdir(parents=True, exist_ok=True)
        with error_log_path.open("w", encoding="utf-8") as f:
            for err in errors:
                f.write(json.dumps({"logged_at": ts, **err}, ensure_ascii=False) + "\n")

    # --- 完了サマリ ----------------------------------------------------------
    print(f"完了: 抽出={len(benchmarks)} 失敗={len(errors)} -> {benchmarks_path}")
    if errors:
        print(f"  エラーログ: {error_log_path}")
