#!/usr/bin/env bash
# SCAM パイプライン: テストデータ (data/test_data/MBDiff_target.json) を対象に
# approach/01..05 と RQ1..RQ3 を順に実行する。
#
# 使い方:
#     bash experiments/scam/scam_pipeline_target.sh
#
# プロジェクトルートからの相対パスを前提とする（実行時の CWD はどこでもよい）。

set -euo pipefail

# このスクリプトのディレクトリを基準にプロジェクトルートを特定
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

ABST_LEVEL="${ABST_LEVEL:-2}"   # RQ3 で参照する固定抽象化レベル（デフォルト A2）

echo "[scam_pipeline_target] PROJECT_ROOT=${PROJECT_ROOT}"
echo "[scam_pipeline_target] target dataset = data/test_data/MBDiff_target.json"
echo

echo "=== Stage 1: cutout ==="
uv run python experiments/scam/approach/01_cutout.py --test

echo
echo "=== Stage 2: abstract ==="
uv run python experiments/scam/approach/02_abstract.py --test

echo
echo "=== Stage 3: detection ==="
uv run python experiments/scam/approach/03_detection.py --test

echo
echo "=== Stage 4: aggregate ==="
uv run python experiments/scam/approach/04_aggregate.py --test

echo
echo "=== Stage 5: score + select ==="
uv run python experiments/scam/approach/05_score_select.py

echo
echo "=== RQ1: size score sensitivity ==="
uv run python experiments/scam/rq1_size_score_sensitivity.py

echo
echo "=== RQ2: abstraction observation ==="
uv run python experiments/scam/rq2_abstraction_observation.py

# echo
# echo "=== RQ3: pattern comparison (abst_level=${ABST_LEVEL}) ==="
# uv run python experiments/scam/rq3_pattern_comparison.py --test --abst-level "${ABST_LEVEL}"

echo
echo "[scam_pipeline_target] DONE"
