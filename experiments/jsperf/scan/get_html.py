"""jsperf.app のサイトマップ XML から HTML を順次取得する．

``data/jsPerf_xml/*.xml`` に列挙された全 URL を ``outputs/scan_jsperf/index.json``
に登録し，未取得分の HTML を 1 件ずつレート制限付きで取得して
``outputs/scan_jsperf/html/<slug>_r<N>.html`` に保存する．

- ``slug`` は URL から ``https://jsperf.app/`` を除去したパス．末尾に ``/N``
  （リビジョン番号）が付かない URL は ``revision=1`` として一律に扱う．
- ``index.json`` は計画と取得状態を 1 ファイルで管理し，アトミック書き換え
  と定期チェックポイントで途中再開を可能にする．
- ファイルシステム上の HTML 実在を起動時にスキャンし，``index.json`` の
  ``status`` を補正する（filesystem が最終真実）．
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from hayalab.config import PathConfig

# --------------------------------------------------------------------------- #
# 取得パラメータ（必要に応じてここで調整）                                       #
# --------------------------------------------------------------------------- #
SLEEP_SECONDS: float = 3.0
"""1 リクエストごとの待機秒数．サイトへの負荷を抑える主要パラメータ．"""

FETCH_LIMIT: int | None = None
"""1 回の実行で取得する最大件数．``None`` で全件．テスト時は 2．"""

USER_AGENT: str = "hayaLab/scan_jsperf research crawler (Wakayama University)"
"""HTTP リクエストの ``User-Agent``．ツール名と所属を明示する．"""

TIMEOUT_SECONDS: float = 30.0
"""HTTP リクエストの個別タイムアウト秒数．"""

RETRY_ATTEMPTS: int = 3
"""一時的失敗時のリトライ回数（指数バックオフ）．"""

RETRY_BACKOFF_SECONDS: float = 5.0
"""リトライ間隔の係数．``attempt * RETRY_BACKOFF_SECONDS`` 秒待つ．"""

CHECKPOINT_EVERY: int = 10
"""この件数ごとに ``index.json`` をアトミック保存する．"""
# --------------------------------------------------------------------------- #


_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>\s*<lastmod>\s*([^<]+?)\s*</lastmod>")
_URL_PREFIX = "https://jsperf.app/"


def _now_utc_iso() -> str:
    """現在時刻 (UTC) を ISO 8601 文字列で返す．

    Returns:
        ``YYYY-MM-DDTHH:MM:SSZ`` 形式の文字列．
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_slug_revision(url: str) -> tuple[str, int]:
    """URL を ``(slug, revision)`` に分解する．

    末尾に ``/N`` (``N`` は整数) が付くものは ``revision=N`` ，付かない場合は
    一律 ``revision=1`` として扱う．

    Args:
        url: ``https://jsperf.app/<slug>[/N]`` 形式の URL．

    Returns:
        ``(slug, revision)`` のタプル．

    Raises:
        ValueError: URL が想定プレフィックスで始まらない場合．
    """
    if not url.startswith(_URL_PREFIX):
        raise ValueError(f"想定外の URL 形式: {url}")
    path = url[len(_URL_PREFIX) :].rstrip("/")
    parts = path.rsplit("/", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    return path, 1


def _html_rel_path(slug: str, revision: int) -> str:
    """``outputs/scan_jsperf/`` 起点での HTML 相対パスを返す．

    Args:
        slug: ベンチマーク slug．``/`` は ``_`` に置換する．
        revision: リビジョン番号．

    Returns:
        ``html/<safe_slug>_r<revision>.html`` 形式の相対パス．
    """
    safe_slug = slug.replace("/", "_")
    return f"html/{safe_slug}_r{revision}.html"


def _compute_summary(entries: list[dict[str, Any]]) -> dict[str, int]:
    """エントリのステータス分布と family 数を集計する．

    Args:
        entries: ``index.json`` の ``entries`` リスト．

    Returns:
        ``total_entries`` / ``unique_families`` / ``fetched`` / ``pending`` /
        ``failed`` をキーに持つ集計辞書．
    """
    families = {e["slug"] for e in entries}
    counts: dict[str, int] = {"fetched": 0, "pending": 0, "failed": 0}
    for e in entries:
        st = e["status"]
        if st in counts:
            counts[st] += 1
    return {
        "total_entries": len(entries),
        "unique_families": len(families),
        **counts,
    }


def _build_index_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """``index.json`` に保存する辞書を組み立てる．

    Args:
        entries: 計画＋取得状態を持つエントリリスト．

    Returns:
        ``generated_at`` / ``source_xml_dir`` / ``config`` / ``summary`` /
        ``entries`` をキーに持つ辞書．
    """
    return {
        "generated_at": _now_utc_iso(),
        "source_xml_dir": "data/jsPerf_xml",
        "config": {
            "sleep_seconds": SLEEP_SECONDS,
            "user_agent": USER_AGENT,
            "timeout_seconds": TIMEOUT_SECONDS,
            "retry_attempts": RETRY_ATTEMPTS,
        },
        "summary": _compute_summary(entries),
        "entries": entries,
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """``tmp → rename`` でアトミックに JSON を書き出す．

    Args:
        path: 出力先パス．親ディレクトリが無ければ作成する．
        payload: シリアライズする辞書．
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _fetch_one(session: requests.Session, url: str) -> tuple[int, str]:
    """単一 URL を取得する（リトライ・指数バックオフ付き）．

    Args:
        session: 共通設定（User-Agent 等）を持つ ``requests.Session``．
        url: 取得対象 URL．

    Returns:
        ``(http_status_code, response_text)`` のタプル．

    Raises:
        RuntimeError: 全リトライが失敗した場合．
    """
    last_err: BaseException | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = session.get(url, timeout=TIMEOUT_SECONDS)
            resp.raise_for_status()
            return resp.status_code, resp.text
        except requests.RequestException as exc:
            last_err = exc
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"取得失敗 ({RETRY_ATTEMPTS} 回): {url}: {last_err}")


if __name__ == "__main__":
    # --- パス決定 ------------------------------------------------------------
    path_config = PathConfig()
    base_dir = path_config.outputs / "jsperf" / "scan"
    xml_dir = path_config.data / "jsPerf" / "xml"
    index_path = base_dir / "index.json"

    # --- XML から計画エントリを構築 -----------------------------------------
    entries: list[dict[str, Any]] = []
    for xml_path in sorted(xml_dir.glob("*.xml")):
        try:
            year = int(xml_path.stem)
        except ValueError:
            continue
        xml_text = xml_path.read_text(encoding="utf-8")
        for m in _LOC_RE.finditer(xml_text):
            url = m.group(1).strip()
            lastmod = m.group(2).strip()
            slug, revision = _parse_slug_revision(url)
            entries.append(
                {
                    "url": url,
                    "slug": slug,
                    "revision": revision,
                    "year": year,
                    "lastmod": lastmod,
                    "html_path": _html_rel_path(slug, revision),
                    "status": "pending",
                    "fetched_at": None,
                    "http_status": None,
                    "error": None,
                }
            )

    # --- 既存 index.json の取得状態をマージ ----------------------------------
    if index_path.is_file():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
        by_url = {e["url"]: e for e in existing.get("entries", [])}
        for e in entries:
            prev = by_url.get(e["url"])
            if prev is None:
                continue
            for key in ("status", "fetched_at", "http_status", "error"):
                if key in prev:
                    e[key] = prev[key]

    # --- ファイルシステムの実在で status を補正 ------------------------------
    for e in entries:
        local_html = base_dir / e["html_path"]
        if local_html.is_file():
            if e["status"] != "fetched":
                e["status"] = "fetched"
                e["fetched_at"] = e.get("fetched_at") or _now_utc_iso()
                e["error"] = None
        else:
            if e["status"] == "fetched":
                e["status"] = "pending"
                e["fetched_at"] = None
                e["http_status"] = None

    # --- 計画＋現状を index.json に保存 --------------------------------------
    _atomic_write_json(index_path, _build_index_payload(entries))

    # --- 未取得を年降順 → slug → revision 昇順で並べて先頭 LIMIT 件を選ぶ ---
    pending = [e for e in entries if e["status"] == "pending"]
    pending.sort(key=lambda e: (-e["year"], e["slug"], e["revision"]))
    todo = pending if FETCH_LIMIT is None else pending[:FETCH_LIMIT]

    summary = _compute_summary(entries)
    print(f"全件: {summary['total_entries']} (families={summary['unique_families']}, fetched={summary['fetched']}, pending={summary['pending']}, failed={summary['failed']})")

    if not todo:
        print("未取得エントリはありません")
        raise SystemExit(0)

    print(f"取得対象: {len(todo)} 件 (sleep={SLEEP_SECONDS}s, limit={FETCH_LIMIT})")

    # --- HTTP セッション準備 & 順次取得ループ --------------------------------
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    since_checkpoint = 0
    for i, entry in enumerate(todo, 1):
        url = entry["url"]
        try:
            status_code, html = _fetch_one(session, url)
            out_html_path = base_dir / entry["html_path"]
            out_html_path.parent.mkdir(parents=True, exist_ok=True)
            out_html_path.write_text(html, encoding="utf-8")
            entry["status"] = "fetched"
            entry["fetched_at"] = _now_utc_iso()
            entry["http_status"] = status_code
            entry["error"] = None
            print(f"  [{i}/{len(todo)}] OK {url} -> {entry['html_path']}")
        except Exception as exc:  # noqa: BLE001 - 取得は何が起きても継続させたい
            entry["status"] = "failed"
            entry["http_status"] = None
            entry["error"] = str(exc)
            print(f"  [{i}/{len(todo)}] NG {url}: {exc}")

        since_checkpoint += 1
        if since_checkpoint >= CHECKPOINT_EVERY:
            _atomic_write_json(index_path, _build_index_payload(entries))
            since_checkpoint = 0

        if i < len(todo):
            time.sleep(SLEEP_SECONDS)

    # --- 最終保存とサマリ出力 ------------------------------------------------
    _atomic_write_json(index_path, _build_index_payload(entries))
    final = _compute_summary(entries)
    print(f"完了: fetched={final['fetched']} pending={final['pending']} failed={final['failed']}")
