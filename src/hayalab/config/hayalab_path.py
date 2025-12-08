from pathlib import Path

# リポジトリ
REPO = Path(__file__).parents[4] / "repository"

# プロジェクト内
ROOT = Path(__file__).parents[3]
# 実験コード
EXPERIMENTS = ROOT / "experiments"
# データ
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
# 結果出力先
OUTPUT = ROOT / "output"

# Hayalabモジュール内
HAYALAB = ROOT / "src" / "hayalab"
