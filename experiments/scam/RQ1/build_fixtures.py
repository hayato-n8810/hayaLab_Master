"""フィクスチャビルダー（テスト補助スクリプト）。

outputs/tmp/previous_ast.json を分解して
tests/tmp/pattern_detection/fixtures/before/ に個別 JSON として保存する。

NOTE: このスクリプトはテスト実行前に手動で一度だけ実行する。
      BEFORE フィクスチャのみ生成する。AFTER フィクスチャはハードコード済み。

Usage:
    uv run python experiments/tmp/slow_pattern_detect/build_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent.parent
SRC_JSON = REPO_ROOT / "outputs" / "tmp" / "previous_ast.json"
FIXTURE_DIR = REPO_ROOT / "tests" / "tmp" / "pattern_detection" / "fixtures" / "before"


def main() -> None:
    """previous_ast.json を分解して id_1〜id_10 を個別 JSON として保存する。"""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    with open(SRC_JSON, encoding="utf-8") as f:
        data = json.load(f)

    for key, value in data.items():
        # key は "id_1", "id_2", ... の形式
        out_path = FIXTURE_DIR / f"{key}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        print(f"Written: {out_path}")

    print(f"Done. {len(data)} fixture(s) written to {FIXTURE_DIR}")


if __name__ == "__main__":
    main()
