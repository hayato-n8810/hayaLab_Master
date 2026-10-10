"""不等価プログラム除外モジュール.

プログラムの決定化 (Babel)、1 回実行による stdout / stderr の観測、
観測値どうしの比較を単体処理として提供する。 実行対象の選択や結果の保存先は
呼び出し側 (`experiments/**`) が決める。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from hayalab.config.hayalab_path import HAYALAB
from hayalab.config.jsperf_config import (
    DETERMINIZE_RANDOM_VALUE,
    DETERMINIZE_TIMESTAMP,
    NODE_BIN,
    NODE_PROGRAM_TIMEOUT_SEC,
)
from hayalab.utils.file.exec import classify_node_error

__all__ = ["replace_non_deterministic", "observe_output", "equivalent_output"]

# --- 実行パラメータ --------------------------------------------------
TIMEOUT_SEC: float = NODE_PROGRAM_TIMEOUT_SEC  # プログラム 1 回の実行
MAX_OLD_SPACE_MB: int = 4096
STDOUT_HEAD_LIMIT: int = 2000
STDERR_HEAD_LIMIT: int = 2000
CHUNK_SIZE: int = 65536

DETERMINIZE_JS: Path = HAYALAB / "jsperf" / "determinize.js"

# ワーカープロセス固有の実行ファイルを置くルート
EXEC_ROOT: Path = Path(tempfile.mkdtemp(prefix="hl_equiv_"))


# --- ヘルパ (複数回呼び出し) ----------------------------------------
def _worker_exec_path() -> Path:
    """呼び出し元プロセス固有の実行ファイルパスを返す.

    同一プロセスで連続実行する限り同じパスになるため、ペアの fast / slow が
    同じ絶対パスで実行され、スタックトレースのパスが一致する。

    Returns:
        `<EXEC_ROOT>/w<pid>/program.js` のパス。
    """
    return EXEC_ROOT / f"w{os.getpid()}" / "program.js"


def _drain(pipe, digest, state: dict, head_limit: int) -> None:
    """パイプを EOF まで読み、ハッシュ・バイト数・先頭文字列を集める.

    Args:
        pipe: 読み出し対象のバイナリパイプ.
        digest: 逐次更新するハッシュオブジェクト.
        state: `bytes` と `head` を書き込む辞書.
        head_limit: 保持する先頭の文字数.
    """
    head = bytearray()
    head_bytes_max = head_limit * 4  # UTF-8 の 1 文字は最大 4 バイト
    total = 0
    for chunk in iter(lambda: pipe.read(CHUNK_SIZE), b""):
        digest.update(chunk)
        total += len(chunk)
        if len(head) < head_bytes_max:
            head.extend(chunk[: head_bytes_max - len(head)])
    state["bytes"] = total
    state["head"] = bytes(head).decode("utf-8", errors="replace")[:head_limit]
    pipe.close()


# --- 単体処理 --------------------------------------------------------
def replace_non_deterministic(code: str, node_bin: str = NODE_BIN) -> tuple[str, str]:
    """プログラムの非決定的な値を Babel で決定化する.

    Args:
        code: 対象プログラムの本体.
        node_bin: 使用する node バイナリ名またはパス.

    Returns:
        `(code, status)` のタプル。 `status` は `"ok"` / `"parse_error"` /
        `"generate_error"`。 失敗時の `code` は元のコードをそのまま返す。

    Raises:
        RuntimeError: determinize.js 自体が異常終了したとき。
    """
    with tempfile.NamedTemporaryFile(suffix=".js", delete=True) as temp_file:
        temp_file.write(code.encode("utf-8"))
        temp_file.flush()
        proc = subprocess.run(
            [node_bin, str(DETERMINIZE_JS), temp_file.name, str(DETERMINIZE_RANDOM_VALUE), str(DETERMINIZE_TIMESTAMP)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    if proc.returncode != 0:
        raise RuntimeError(f"determinize.js failed (exit={proc.returncode}): {proc.stderr[:500]}")

    result = json.loads(proc.stdout)
    return result["code"], result["status"]


def observe_output(
    program: str,
    js_path: Path,
    node_bin: str = NODE_BIN,
    timeout: float | None = TIMEOUT_SEC,
    env: dict[str, str] | None = None,
) -> dict:
    """JS を 1 回実行し、stdout / stderr のハッシュと終了状態を返す.

    stdout と stderr をスレッド 2 本で並行に読みながらハッシュ化するため、
    出力をメモリにもディスクにも溜めない。

    Args:
        program: 実行対象の JS プログラム.
        js_path: プログラムを書き出して実行するパス.
        node_bin: 使用する node バイナリ名またはパス.
        timeout: タイムアウト時間 (秒). `None` の場合はタイムアウトなし.
        env: 子プロセスの環境変数. `None` なら親から継承する.

    Returns:
        `status` (`"success"` / `"error"` / `"timeout"`), `exit_code`,
        `stdout_sha256`, `stderr_sha256`, `stdout_bytes`, `stderr_bytes`,
        `stdout_head`, `stderr_head`, `error_type`, `elapsed` を持つ辞書。
    """
    js_path.parent.mkdir(parents=True, exist_ok=True)
    js_path.write_text(program, encoding="utf-8")

    stdout_digest = hashlib.sha256()
    stderr_digest = hashlib.sha256()
    stdout_state: dict = {"bytes": 0, "head": ""}
    stderr_state: dict = {"bytes": 0, "head": ""}

    start = time.perf_counter()
    proc = subprocess.Popen(
        [node_bin, "--no-warnings", f"--max-old-space-size={MAX_OLD_SPACE_MB}", str(js_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    out_thread = threading.Thread(target=_drain, args=(proc.stdout, stdout_digest, stdout_state, STDOUT_HEAD_LIMIT), daemon=True)
    err_thread = threading.Thread(target=_drain, args=(proc.stderr, stderr_digest, stderr_state, STDERR_HEAD_LIMIT), daemon=True)
    out_thread.start()
    err_thread.start()

    timed_out = False
    try:
        exit_code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        exit_code = proc.wait()
    out_thread.join()
    err_thread.join()
    elapsed = time.perf_counter() - start

    if timed_out:
        status = "timeout"
    elif exit_code == 0:
        status = "success"
    else:
        status = "error"

    return {
        "status": status,
        "exit_code": None if timed_out else exit_code,
        "stdout_sha256": stdout_digest.hexdigest(),
        "stderr_sha256": stderr_digest.hexdigest(),
        "stdout_bytes": stdout_state["bytes"],
        "stderr_bytes": stderr_state["bytes"],
        "stdout_head": stdout_state["head"],
        "stderr_head": stderr_state["head"],
        "error_type": classify_node_error(stderr_state["head"]) if status == "error" else None,
        "elapsed": elapsed,
    }


def equivalent_output(fast_code: str, slow_code: str) -> tuple[bool, str | None, dict, dict]:
    """2 つのプログラムを実行し、標準出力が等価かどうかと理由を返す.

    fast / slow を同一プロセスの同一パスで連続実行するため、
    スタックトレースに現れる絶対パスが両者で一致する。

    Args:
        fast_code: fast 側のプログラム.
        slow_code: slow 側のプログラム.

    Returns:
        `(等価か, 理由, fast の観測値, slow の観測値)` のタプル。
        等価なら理由は `None`、非等価なら `"verification_failed"` /
        `"exit_status_mismatch"` / `"stdout_mismatch"` / `"stderr_mismatch"`。
    """
    js_path = _worker_exec_path()
    fast_program = "(function () {\n" + fast_code + "\n})();\n"
    slow_program = "(function () {\n" + slow_code + "\n})();\n"
    obs_fast = observe_output(fast_program, js_path)
    obs_slow = observe_output(slow_program, js_path)

    if obs_fast["status"] != "success" or obs_slow["status"] != "success":
        return False, "verification_failed", obs_fast, obs_slow
    if obs_fast["exit_code"] != obs_slow["exit_code"]:
        return False, "exit_status_mismatch", obs_fast, obs_slow
    if obs_fast["stdout_sha256"] != obs_slow["stdout_sha256"]:
        return False, "stdout_mismatch", obs_fast, obs_slow
    if obs_fast["stderr_sha256"] != obs_slow["stderr_sha256"]:
        return False, "stderr_mismatch", obs_fast, obs_slow
    return True, None, obs_fast, obs_slow


def compare_return(programs1, programs2):
    """戻り値を比較する"""


def equivalent_value(programs1, programs2):
    """実行終了時の変数の最終格納値を比較する"""


def equivalent_formula(programs1, programs2):
    """式の値を比較する"""
