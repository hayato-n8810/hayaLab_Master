"""外部プロセス実行（Node）の薄いラッパと stderr 分類の純粋関数群。

パス決定や出力先の判断は行わない。 呼び出し側（experiments/**）が組み立てる。
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

STDERR_HEAD_LIMIT: int = 2000


def classify_node_error(stderr: str) -> str:
    """Node の stderr 文字列から error_type を分類する.

    Args:
        stderr: `node` 実行時の標準エラー出力.

    Returns:
        str: `ModuleNotFound` / `OutOfMemory` / `ReferenceError` /
        `TypeError` / `SyntaxError` / `RangeError` / `OtherError`
        のいずれか (具体的なパターンから順に判定).
    """
    if not stderr:
        return "OtherError"
    if "Cannot find module" in stderr:
        return "ModuleNotFound"
    if "JavaScript heap out of memory" in stderr:
        return "OutOfMemory"
    if "ReferenceError" in stderr:
        return "ReferenceError"
    if "TypeError" in stderr:
        return "TypeError"
    if "SyntaxError" in stderr:
        return "SyntaxError"
    if "RangeError" in stderr:
        return "RangeError"
    return "OtherError"


def run_node(js_path: Path, node_bin: str = "node", timeout: float | None = None) -> dict:
    """`node <js_path>` を 1 回実行し、実行結果を辞書で返す.

    Args:
        js_path: 実行対象の JS ファイルパス.
        node_bin: 使用する node バイナリ名またはパス.
        timeout: タイムアウト時間 (秒). `None` の場合はタイムアウトなし.

    Returns:
        dict: `status` (`success` / `error` / `timeout`), `exit_code`
        (timeout の場合は `None`), `stderr_head` (先頭 2000 文字), `elapsed` (秒)
        を持つ辞書.
    """
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            [node_bin, str(js_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.perf_counter() - start
        stderr = e.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return {
            "status": "timeout",
            "exit_code": None,
            "stderr_head": stderr[:STDERR_HEAD_LIMIT],
            "elapsed": elapsed,
        }
    elapsed = time.perf_counter() - start
    stderr_head = (proc.stderr or "")[:STDERR_HEAD_LIMIT]
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "exit_code": proc.returncode,
        "stderr_head": stderr_head,
        "elapsed": elapsed,
    }
