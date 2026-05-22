#!/usr/bin/env bash
# SCAM パイプライン: 本番データ (data/processed/MBDiff.json) を対象に
# approach/01..05 と RQ1..RQ3 を順に実行する。
#
# 使い方:
#     bash experiments/scam/scam_pipeline_all.sh
#     WORKERS=40 ABST_LEVEL=2 bash experiments/scam/scam_pipeline_all.sh
#
# 環境変数:
#     WORKERS     : Stage 3 (detection) の並列ワーカー数（デフォルト: 40）
#     ABST_LEVEL  : RQ3 で参照する固定抽象化レベル（デフォルト: 2）

set -euo pipefail

# このスクリプトのディレクトリを基準にプロジェクトルートを特定
PROJECT_ROOT="/works"
cd "${PROJECT_ROOT}"

WORKERS="${WORKERS:-40}"
ABST_LEVEL="${ABST_LEVEL:-2}"

echo "[scam_pipeline_all] PROJECT_ROOT=${PROJECT_ROOT}"
echo "[scam_pipeline_all] production dataset = data/processed/MBDiff.json"
echo "[scam_pipeline_all] WORKERS=${WORKERS}  ABST_LEVEL=${ABST_LEVEL}"
echo

echo "=== Stage 1: cutout ==="
python3 experiments/scam/approach/01_cutout.py

echo
echo "=== Stage 2: abstract ==="
python3 experiments/scam/approach/02_abstract.py

echo
echo "=== Stage 3: detection (workers=${WORKERS}) ==="
python3 experiments/scam/approach/03_detection.py --workers "${WORKERS}"

echo
echo "=== Stage 4: aggregate ==="
python3 experiments/scam/approach/04_aggregate.py

echo
echo "=== Stage 5: score + select ==="
python3 experiments/scam/approach/05_score_select.py

echo
echo "=== RQ1: size score sensitivity ==="
python3 experiments/scam/rq1_size_score_sensitivity.py

echo
echo "=== RQ2: abstraction observation ==="
python3 experiments/scam/rq2_abstraction_observation.py

# echo
# echo "=== RQ3: pattern comparison (abst_level=${ABST_LEVEL}) ==="
# python3 experiments/scam/rq3_pattern_comparison.py --abst-level "${ABST_LEVEL}"

echo
echo "[scam_pipeline_all] DONE"
