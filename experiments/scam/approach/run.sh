#!/bin/sh
# approach 実行パイプライン
# cutout → abstract → integrate (clustering + bigram cache) → show_label → Representative_value
#
# 出力先:
#   cutout:               outputs/scam/approach/cutouts.json
#   abstract:             outputs/scam/approach/abstract/abstract_level{L}.json
#   integrate:            outputs/scam/approach/integrate/jaccard{NN}/level{L}/{depth}/{depth}.json
#   show_label:           outputs/scam/approach/integrate/jaccard{NN}/level{L}/{depth}/{depth}_label.json
#   Representative_value: outputs/scam/approach/integrate/jaccard{NN}/level{L}/{depth}/{depth}_pattern_mode_medoid.json
#
# 実行例（論文再現: τ ∈ {0.7, 0.9}）:
#   sh   experiments/scam/approach/run.sh
#   bash experiments/scam/approach/run.sh
#
# 探索的に複数 tau を見る場合（TAUS は空白区切り）:
#   TAUS="0.5 0.7 0.9" bash experiments/scam/approach/run.sh

set -eu

# 念のため CWD をリポジトリルートに揃える（このスクリプトは repo root からの
# 相対パスを前提に書かれている）。
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
cd "${REPO_ROOT}"

# 共通パラメタ（環境変数で上書き可能）
N=2
TAUS="${TAUS:-0.7 0.9}"
LEVELS="${LEVELS:-1 2}"
DEPTHS="${DEPTHS:-Diff Brother ExParent Parent}"
WORKERS="${WORKERS:-40}"

# TAUS から TAU_DIRS を導出（0.7 → jaccard07, 1.0 → jaccard10）。
TAU_DIRS=""
for t in ${TAUS}; do
    nn=$(printf "%s" "${t}" | awk '{ printf("%02d", $1 * 10 + 0.5) }')
    TAU_DIRS="${TAU_DIRS}jaccard${nn} "
done
TAU_DIRS=$(printf "%s" "${TAU_DIRS}" | sed 's/ *$//')

CUTOUT=experiments/scam/approach/cutout.py
ABSTRACT=experiments/scam/approach/abstract.py
INTEGRATE=experiments/scam/approach/integrate.py
SHOW_LABEL=experiments/scam/approach/show_label.py
REPV=experiments/scam/approach/Representative_value

echo "[CONFIG] CWD=${REPO_ROOT}"
echo "[CONFIG] N=${N} TAUS=${TAUS} TAU_DIRS=${TAU_DIRS} LEVELS=${LEVELS} WORKERS=${WORKERS}"

# 1. cutout: AST cutout を生成
echo
echo "================================================================"
echo "  STEP 1/5: cutout.py"
echo "================================================================"
python3 "${CUTOUT}" \
    --workers ${WORKERS}

# 2. abstract: AST cutout から抽象化 JSON を生成（--server で全レベル並列）
echo
echo "================================================================"
echo "  STEP 2/5: abstract.py --server"
echo "================================================================"
python3 "${ABSTRACT}" \
    --workers ${WORKERS} \
    --server

# 3. integrate: complete-linkage クラスタリング（複数 tau を一括）
#    bigram cache pickle が必要な場合は末尾に --create-cache を追加する。
echo
echo "================================================================"
echo "  STEP 3/5: integrate.py"
echo "================================================================"
python3 "${INTEGRATE}" \
    --levels ${LEVELS} \
    --n ${N} \
    --taus ${TAUS} \
    --workers ${WORKERS} \
    # --create-cache \

# 4. show_label: tau_dir ごとに label JSON を生成
echo
echo "================================================================"
echo "  STEP 4/5: show_label.py (per tau_dir)"
echo "================================================================"
for tau_dir in ${TAU_DIRS}; do
    python3 "${SHOW_LABEL}" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS}
done

# 5. Representative_value: mode_medoid を全 tau_dir 一括
echo
echo "================================================================"
echo "  STEP 5/5: Representative_value (mode_medoid)"
echo "================================================================"
for tau_dir in ${TAU_DIRS}; do
    echo
    echo "  --- tau_dir = ${tau_dir} ---"
    python3 "${REPV}/mode_medoid.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --workers ${WORKERS}
done

echo
echo "[DONE] approach: all steps finished."
