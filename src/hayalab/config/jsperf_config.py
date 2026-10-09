"""jsPerf 共通設定値"""

from __future__ import annotations

# --- 実行環境 ---
NODE_BIN: str = "node"

# --- エラー分類キー (classify_node_error の返り値と対応) ---
NODE_ERROR_TYPE_KEYS: tuple[str, ...] = (
    "ReferenceError",
    "TypeError",
    "SyntaxError",
    "RangeError",
    "ModuleNotFound",
    "OutOfMemory",
    "Timeout",
    "OtherError",
)
PLAYWRIGHT_ERROR_TYPE_KEYS: tuple[str, ...] = (
    "LoadFailed",
    "Timeout",
    "ScriptLoadFailed",
    "PageError",
    "ConsoleError",
    "DriverCrashed",
)

# --- ペア生成条件 ---
CONFIDENCE: float = 0.95

# --- 決定化条件 ---
DETERMINIZE_RANDOM_VALUE: float = 0.5
DETERMINIZE_TIMESTAMP: int = 1700000000000

# タイムアウトの基準: プログラムを 1 回実行するのに許す秒数
NODE_PROGRAM_TIMEOUT_SEC: float = 180.0
PLAYWRIGHT_PROGRAM_TIMEOUT_SEC: float = 180.0
