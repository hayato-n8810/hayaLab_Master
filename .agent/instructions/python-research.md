# Python and Analysis File Instructions

Apply when editing: `src/**/*.py`, `QL/scripts/**/*.py`, `experiments/**/*.py`

- Do not enforce strict function size limits; prefer grouping cohesive processing into a single function when it improves clarity.
- When behavior changes, clearly describe what changed. Adding tests or quick validation code is not required.
- Follow Ruff settings defined in `pyproject.toml`.
- Keep CLI scripts idempotent where possible.
- Validate file existence before reading and create output directories before writing.
- Use UTF-8 for text files and explicit encoding in open calls.
- Avoid hard-coded absolute paths unless they are configuration values.
- Use Google-style docstrings.
- Use uv-managed workflow commands for Python dependencies and execution, such as `uv add` and `uv run`.
- When changing output JSON structure, document backward compatibility impact in the response.
- Prefer deterministic ordering for serialized outputs (for reproducible diffs).

## Directory Boundaries (where to implement)

- `src/hayalab/**` (library)
	- Put reusable logic here. Keep functions composable and focused (one processing unit per function where practical).
	- Do not decide concrete input/output paths here; take data/paths as arguments and return results.
	- Avoid importing `experiments/**`. Dependency direction is `experiments -> hayalab`.
	- Keep side effects minimal; printing/logging should be opt-in (or handled by callers).

- `experiments/**` (experiment runners)
	- Put experiment-specific orchestration here: CLI args, path selection, I/O formats, and execution order.
	- Keep the code thin: read inputs, call `hayalab`, write outputs.
	- It is OK to hard-code paths relative to repo root (e.g., `data/`, `outputs/`) when that is the experiment contract.

- `QL/scripts/**` (automation / batch utilities)
	- Put CodeQL execution helpers, conversions (e.g., SARIF -> JSON), and aggregations here.
	- Prefer CLI-friendly interfaces and idempotent behavior (safe re-runs).

## I/O and Schema Rules

- Experiments own file layout decisions; the library should not write into `outputs/**` or `data/**` by default.
- If you must add a new output file, place it under the existing `outputs/**` conventions and keep naming stable.
- When changing JSON schema, keep downstream compatibility in mind (key names, list ordering, and sorting).

## Experiment Script Structure (`experiments/**/*.py`)

実験スクリプトは「上から読めば全フローが追える」ことを最優先する．抽象化は再利用が発生したときのみ導入する．

### 必須ルール

1. **`main()` 関数を作らない**: 実行フローは `if __name__ == "__main__":` ブロックに直接書く．モジュールトップレベルに `def main(): ...` を置いて末尾で呼ぶ構造は使わない．
2. **1度しか呼ばれない処理を関数に切り出さない**: 単一の処理ステップは `__main__` ブロック内にインラインで記述する．「リーダブルな名前を付けたいから」だけの理由で関数化しない．
3. **関数として残してよいのは以下のみ**:
   - 複数回呼ばれるユーティリティ（タイムスタンプ生成・パス計算・JSON 保存等）
   - per-entry / per-URL / per-record のワーカー（リトライ・パース・抽出など，ループ内で 1 件ずつ呼ばれる処理）
   - 共通の組み立て処理（payload 構築など，複数箇所で同じ辞書/構造を作る場合）
4. **`__main__` ブロックは「セクションコメント＋線形フロー」で記述**: 区切りコメント (`# --- セクション名 -----`) を入れ，処理ブロックを上から順に並べる．早期終了が必要な箇所では `raise SystemExit(0)` を使ってよい．

### 推奨パターン

```python
"""モジュール docstring（Google スタイル）．"""

from __future__ import annotations
import ...

# --- 定数（コード冒頭で調整可能なハイパーパラメータ）----
PARAM_A: int = ...

# --- ヘルパー（複数回呼ばれるもののみ）------------------
def _helper_called_many_times(...) -> ...:
    """Google スタイル docstring (Args/Returns/Raises)．"""
    ...

def _worker_per_record(...) -> ...:
    """per-entry の処理（ループ内で呼ばれる）．"""
    ...

# --- メインフロー -----------------------------------------
if __name__ == "__main__":
    # --- セクション 1: パス決定 ---
    ...

    # --- セクション 2: 入力読み込み ---
    ...

    # --- セクション 3: メインループ ---
    for entry in entries:
        _worker_per_record(entry)
        ...

    # --- セクション 4: 出力保存 ---
    ...
```

### 判断基準（関数化すべきか）

- 「2 回以上呼ばれる？」→ Yes なら関数化
- 「ループ本体になるか？」（per-record 処理）→ Yes なら関数化してテスト/再利用に備える
- 「`__main__` の中で意味のあるまとまりを名前で示したいだけ？」→ No．**セクションコメントで代替**する
- 「失敗時のリカバリ処理が複雑？」→ Yes ならワーカー関数化して `try/except` を整理
