#!/bin/sh
# approach実行パイプライン
# cutout → abstract → integrate (clustering + bigram cache) → show_label → Representative_value
# 出力先:
#   cutout:          outputs/scam/approach/cutouts.json
#   abstract:        outputs/scam/approach/abstract/abstract_level{L}.json
#   integrate:        outputs/scam/approach/integrate/jaccard{07,09}/level{L}/{depth}.json
#   show_label:       outputs/scam/approach/integrate/jaccard{07,09}/level{L}/{depth}_label.json
#   Representative_value: outputs/scam/approach/integrate/jaccard{07,09}/level{L}/{depth}_pattern_{strategy}.json
#
# 実行例:
#   sh   experiments/scam/approach/run.sh
#   bash experiments/scam/approach/run.sh

set -eu

# 念のため CWD をリポジトリルートに揃える（このスクリプトは repo root からの
# 相対パスを前提に書かれている）。
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
cd "${REPO_ROOT}"

# 共通パラメタ
N=2
TAUS="0.5 0.6 0.7 0.8 0.9 1.0"
TAU_DIRS="jaccard05 jaccard06 jaccard07 jaccard08 jaccard09 jaccard10"   # integrate.py:_tau_dirname(0.7)=jaccard07
LEVELS="1 2"
DEPTHS="Diff Brother ExParent Parent"
WORKERS=40

CUTOUT=experiments/scam/approach/cutout.py
ABSTRACT=experiments/scam/approach/abstract.py
INTEGRATE=experiments/scam/approach/integrate.py
SHOW_LABEL=experiments/scam/approach/show_label.py
REPV=experiments/scam/approach/Representative_value

echo "[CONFIG] CWD=${REPO_ROOT}"
echo "[CONFIG] N=${N} TAUS=${TAUS} LEVELS=${LEVELS} WORKERS=${WORKERS}"

# 1. cutout: AST cutout を生成
echo
echo "================================================================"
echo "  STEP 1/5: cutout.py"
echo "================================================================"
python3 "${CUTOUT}" \
    --workers ${WORKERS}

# 2. abstract: AST cutout から抽象化 JSON を生成
echo
echo "================================================================"
echo "  STEP 2/5: abstract.py"
echo "================================================================"
for level in ${LEVELS}; do
    python3 "${ABSTRACT}" \
        --workers ${WORKERS} \
        --server
done

# 3. integrate: クラスタリング (--server) + bigram cache 生成 (--create-cache)
echo
echo "================================================================"
echo "  STEP 3/5: integrate.py --create-cache"
echo "================================================================"
python3 "${INTEGRATE}" \
    --levels ${LEVELS} \
    --n ${N} \
    --taus ${TAUS} \
    --workers ${WORKERS}
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

# 5. Representative_value: 4 戦略 × tau_dir
echo
echo "================================================================"
echo "  STEP 5/5: Representative_value "
echo "================================================================"
for tau_dir in ${TAU_DIRS}; do
    echo
    echo "  --- tau_dir = ${tau_dir} ---"

    # mode + medoid （cache hit）
    python3 "${REPV}/mode_medoid.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --workers ${WORKERS}

done

echo
echo "[DONE] approach: all steps finished."
