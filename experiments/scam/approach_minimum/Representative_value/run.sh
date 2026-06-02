#!/bin/sh
# Representative_value: 4 戦略 × 3 tau_dir × 4 level × 4 depth の代表 value 抽出を一括実行する。
#
# 前提:
#   - integrate.py が {tau_dir}/level{L}/{depth}.json を生成済み
#   - show_label.py が {tau_dir}/level{L}/{depth}_label.json を生成済み
#
# 未生成の (tau_dir, level, depth) は各スクリプト内で [SKIP] される。
#
# 環境変数による上書き:
#   TAU_DIRS  : 処理する jaccard ディレクトリ群 (default: "jaccard05 jaccard07 jaccard09")
#   LEVELS    : 処理する level 群 (default: "0 1 2 3")
#   DEPTHS    : 処理する depth 群 (default: "Diff Brother ExParent Parent")
#   SKELETON_K   : skeleton.py の --k (default: 0.66)
#   OUTLIER_TAU  : medoid_outlier.py の --outlier-tau (default: 0.5)
#   WORKERS      : 各戦略の --workers (default: 未指定 → Python 側 os.cpu_count())
#
# 実行例（リポジトリルートで実行）:
#   sh   experiments/scam/approach_minimum/Representative_value/run.sh
#   bash experiments/scam/approach_minimum/Representative_value/run.sh
#   WORKERS=8 TAU_DIRS="jaccard07" LEVELS="0" \
#       sh experiments/scam/approach_minimum/Representative_value/run.sh

set -eu

TAU_DIRS="${TAU_DIRS:-jaccard05 jaccard07 jaccard09}"
LEVELS="${LEVELS:-0 1 2 3}"
DEPTHS="${DEPTHS:-Diff Brother ExParent Parent}"
SKELETON_K="${SKELETON_K:-0.66}"
OUTLIER_TAU="${OUTLIER_TAU:-0.5}"

BASE="experiments/scam/approach_minimum/Representative_value"

# POSIX shell には bash 配列が無いので、文字列として組み立てて
# unquoted 展開で word-split させる（WORKERS は数値しか入らないので安全）。
# WORKERS_ARG=""
# if [ -n "${WORKERS:-}" ]; then
#     WORKERS_ARG="--workers ${WORKERS}"
# fi

echo "[CONFIG] TAU_DIRS=${TAU_DIRS}"
echo "[CONFIG] LEVELS=${LEVELS}"
echo "[CONFIG] DEPTHS=${DEPTHS}"
echo "[CONFIG] SKELETON_K=${SKELETON_K}  OUTLIER_TAU=${OUTLIER_TAU}"
echo "[CONFIG] WORKERS=${WORKERS:-(auto)}"

for tau_dir in ${TAU_DIRS}; do
    echo
    echo "================================================================"
    echo "  tau_dir = ${tau_dir}"
    echo "================================================================"

    # 戦略 1: mode + medoid
    python3 "${BASE}/mode_medoid.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --workers 40

    # 戦略 2: 共通 bigram
    python3 "${BASE}/common_bigrams.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --workers 40

    # 戦略 3: スケルトン
    python3 "${BASE}/skeleton.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --k "${SKELETON_K}" \
        --workers 40

    # 戦略 4: medoid + 外れ値
    python3 "${BASE}/medoid_outlier.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --outlier-tau "${OUTLIER_TAU}" \
        --workers 40
done

echo
echo "[DONE] Representative_value: all strategies finished."
