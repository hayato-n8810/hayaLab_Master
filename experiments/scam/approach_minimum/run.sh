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
#   cutout:          outputs/scam/approach_minimum/cutouts.json
#   abstract:        outputs/scam/approach_minimum/abstract/abstract_level{L}.json
#   integrate:        outputs/scam/approach_minimum/integrate/jaccard{07,09}/level{L}/{depth}.json
#   show_label:       outputs/scam/approach_minimum/integrate/jaccard{07,09}/level{L}/{depth}_label.json
#   Representative_value: outputs/scam/approach_minimum/integrate/jaccard{07,09}/level{L}/{depth}_pattern_{strategy}.json
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
# paper §6.3.1 の確定方針 (2 軸: 抽象化 × 類似度) に従い、 メイン分析は
# L0/L1 のみを対象とする。 L2/L3 は paper §6.3.1 の「不採用の論証根拠」
# (E2 §4.2.2 の L1↔L2 等価性、 E4 §5.3 の L3 擬似クラスタ問題) の再現が
# 必要な場合のみ手動で ``LEVELS="0 1 2 3"`` に切り替えて実行する。
LEVELS="0 1"
DEPTHS="Diff Brother ExParent Parent"
WORKERS=40

CUTOUT=experiments/scam/approach_minimum/cutout.py
ABSTRACT=experiments/scam/approach_minimum/abstract.py
INTEGRATE=experiments/scam/approach_minimum/integrate.py
SHOW_LABEL=experiments/scam/approach_minimum/show_label.py
REPV=experiments/scam/approach_minimum/Representative_value

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
        --level ${level} \
        --workers ${WORKERS} \
        --server
done

# 3. integrate: クラスタリング (--server) + bigram cache 生成 (--create-cache)
echo
echo "================================================================"
echo "  STEP 3/5: integrate.py --server --create-cache"
echo "================================================================"
python3 "${INTEGRATE}" \
    --server \
    --create-cache \
    --levels ${LEVELS} \
    --n ${N} \
    --taus ${TAUS} \
    --workers ${WORKERS}

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
echo "  STEP 5/5: Representative_value (4 strategies per tau_dir)"
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
echo "[DONE] approach_minimum: all steps finished."
