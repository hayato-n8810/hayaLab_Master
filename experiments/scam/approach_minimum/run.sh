#!/bin/sh
# approach_minimum: integrate → show_label → Representative_value を連続実行する。
#
# 想定 CWD: リポジトリルート
# n=2 の bigram、 taus は 0.7 と 0.9、 workers は 40。
# integrate は --server --create-cache を付け、 cache pickle
# (outputs/scam/approach_minimum/abstract/bigrams_level{L}_n2.pkl) を生成する。
# 以降の戦略は cache を消費する（mode_medoid / common_bigrams は cache hit、
# skeleton_node は bigram 不使用なので abstract JSON を直接読む）。
#
# 出力先:
#   integrate:        outputs/scam/approach_minimum/integrate/jaccard{07,09}/level{L}/{depth}.json
#   show_label:       outputs/scam/approach_minimum/integrate/jaccard{07,09}/level{L}/{depth}_label.json
#   Representative_value: outputs/scam/approach_minimum/integrate/jaccard{07,09}/level{L}/{depth}_pattern_{strategy}.json
#
# 前提:
#   - outputs/scam/approach_minimum/abstract/abstract_level{0,1,2,3}.json が存在
#     （cutout.py + abstract.py で事前生成済み）
#
# 実行例:
#   sh   experiments/scam/approach_minimum/run.sh
#   bash experiments/scam/approach_minimum/run.sh

set -eu

# 念のため CWD をリポジトリルートに揃える（このスクリプトは repo root からの
# 相対パスを前提に書かれている）。
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
cd "${REPO_ROOT}"

# 共通パラメタ
N=2
TAUS="0.7 0.9"
TAU_DIRS="jaccard07 jaccard09"   # integrate.py:_tau_dirname(0.7)=jaccard07, _tau_dirname(0.9)=jaccard09
LEVELS="0 1 2 3"
DEPTHS="Diff Brother ExParent Parent"
WORKERS=40
SKELETON_K=0.66

INTEGRATE=experiments/scam/approach_minimum/integrate.py
SHOW_LABEL=experiments/scam/approach_minimum/show_label.py
REPV=experiments/scam/approach_minimum/Representative_value

echo "[CONFIG] CWD=${REPO_ROOT}"
echo "[CONFIG] N=${N} TAUS=${TAUS} LEVELS=${LEVELS} WORKERS=${WORKERS}"

# 1. integrate: クラスタリング (--server) + bigram cache 生成 (--create-cache)
echo
echo "================================================================"
echo "  STEP 1/3: integrate.py --server --create-cache"
echo "================================================================"
python3 "${INTEGRATE}" \
    --server \
    --create-cache \
    --levels ${LEVELS} \
    --n ${N} \
    --taus ${TAUS} \
    --workers ${WORKERS}

# 2. show_label: tau_dir ごとに label JSON を生成
echo
echo "================================================================"
echo "  STEP 2/3: show_label.py (per tau_dir)"
echo "================================================================"
for tau_dir in ${TAU_DIRS}; do
    python3 "${SHOW_LABEL}" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS}
done

# 3. Representative_value: 4 戦略 × tau_dir
echo
echo "================================================================"
echo "  STEP 3/3: Representative_value (4 strategies per tau_dir)"
echo "================================================================"
for tau_dir in ${TAU_DIRS}; do
    echo
    echo "  --- tau_dir = ${tau_dir} ---"

    # 戦略 1: スケルトン (label value トークン)
    python3 "${REPV}/skeleton.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --k "${SKELETON_K}" \
        --workers ${WORKERS}

    # # 戦略 2: 共通 bigram （cache hit）
    # python3 "${REPV}/common_bigrams.py" \
    #     --tau-dir "${tau_dir}" \
    #     --levels ${LEVELS} \
    #     --depths ${DEPTHS} \
    #     --workers ${WORKERS}

    # 戦略 3: mode + medoid （cache hit）
    python3 "${REPV}/mode_medoid.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --workers ${WORKERS}

    # 戦略 4: スケルトン (AST node 列、 cache 不使用で abstract を読む)
    python3 "${REPV}/skeleton_node.py" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS} \
        --depths ${DEPTHS} \
        --k "${SKELETON_K}" \
        --workers ${WORKERS}
done

echo
echo "[DONE] approach_minimum: all steps finished."
