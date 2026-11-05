import atexit
import json
import subprocess

from hayalab.config.hayalab_path import UTILS

# プロセスごとに 1 つ常駐させる file_clean.js のワーカー
_worker: subprocess.Popen | None = None


def _close_worker() -> None:
    """常駐ワーカーを終了する."""
    global _worker
    if _worker is not None:
        _worker.stdin.close()
        _worker.wait()
        _worker = None


atexit.register(_close_worker)


def code_clean(code: str) -> str:
    """コードの前処理を行う関数

    常駐させた `file_clean.js` で改行コードの標準化・prettier・コメント除去・空行の除去を適用する。

    Args:
        code (str): 元のJavaScriptコード

    Returns:
        str: 前処理後のJavaScriptコード。整形・解析に失敗した場合は空文字列
    """
    global _worker
    if _worker is None or _worker.poll() is not None:
        _worker = subprocess.Popen(
            ["node", str(UTILS / "file" / "file_clean.js")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
    try:
        _worker.stdin.write(json.dumps({"code": code}) + "\n")
        _worker.stdin.flush()
        line = _worker.stdout.readline()
    except BrokenPipeError:
        line = ""
    if not line:
        # ワーカーが異常終了した場合は次回呼び出しで再起動する
        _worker.kill()
        _worker = None
        return ""
    return json.loads(line)["code"] or ""
