#!/bin/sh
# approach_minimum (complete-linkage 版): integrate_complete → Representative_value を実行する。
#
# run.sh の single-linkage パイプラインに対し、本スクリプトはクラスタ内全ペアが
# tau 以上を保証する complete-linkage 版 (integrate_complete.py) を使う。
#
# 想定 CWD: リポジトリルート
# n=2 の bigram、 taus は 0.7 と 0.9、 workers は 40。
#
# 【前提】cutout / abstract / bigram cache は run.sh で生成済みであること。
#   - cutouts:  outputs/scam/approach_minimum/cutouts.json
#   - abstract: outputs/scam/approach_minimum/abstract/abstract_level{L}.json
#   - cache:    outputs/scam/approach_minimum/abstract/bigrams_level{L}_n2.pkl
#   これらは single / complete で共通のため再生成しない（integrate_complete は
#   cache を読むのみ。--create-cache は付けない）。run.sh を一度も流していない
#   場合は先に run.sh（STEP1〜3）を実行すること。
#
# 出力先:
#   integrate_complete:   outputs/scam/approach_minimum/integrate_complete/jaccard{07,09}/level{L}/{depth}/{depth}.json
#   Representative_value: 下流スクリプト側のパス対応に従う
#
# 実行例:
#   sh   experiments/scam/approach_minimum/run_complete.sh
#   bash experiments/scam/approach_minimum/run_complete.sh

set -eu

# 念のため CWD をリポジトリルートに揃える（このスクリプトは repo root からの
# 相対パスを前提に書かれている）。
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../../.." && pwd)
cd "${REPO_ROOT}"

# 共通パラメタ（run.sh と揃える）
N=2
TAUS="0.5 0.6 0.8 1.0"   # run.sh では 0.5 を integrate.py のみで使うが、 complete-linkage 版では全ての tau で同じ出力ディレクトリ構造にするため全 tau を指定する。`"
TAU_DIRS="jaccard05 jaccard06 jaccard08 jaccard10"   # integrate.py:_tau_dirname(0.5)=jaccard05, _tau_dirname(0.6)=jaccard06, _tau_dirname(0.8)=jaccard08, _tau_dirname(1.0)=jaccard10
# paper §6.3.1 の確定方針に従い、 メイン分析は L0/L1 のみを対象とする。
LEVELS="0 1"
DEPTHS="Diff Brother ExParent Parent"
WORKERS=32

INTEGRATE_COMPLETE=experiments/scam/approach_minimum/integrate_complete.py
SHOW_LABEL=experiments/scam/approach_minimum/show_label.py
REPV=experiments/scam/approach_minimum/Representative_value

echo "[CONFIG] CWD=${REPO_ROOT}"
echo "[CONFIG] MODE=complete-linkage N=${N} TAUS=${TAUS} LEVELS=${LEVELS} WORKERS=${WORKERS}"

# 1. integrate_complete: complete-linkage クラスタリング (cache 流用、--create-cache なし)
echo
echo "================================================================"
echo "  STEP 1/3: integrate_complete.py (complete-linkage)"
echo "================================================================"
python3 "${INTEGRATE_COMPLETE}" \
    --levels ${LEVELS} \
    --n ${N} \
    --taus ${TAUS} \
    --workers ${WORKERS}

# 2. show_label: tau_dir ごとに label JSON を生成（mode_medoid が label を要求するため）
#    （integrate_complete の出力を読むためのパス対応は show_label 側で行う）
echo
echo "================================================================"
echo "  STEP 2/3: show_label.py (per tau_dir)"
echo "================================================================"
for tau_dir in ${TAU_DIRS}; do
    python3 "${SHOW_LABEL}" \
        --tau-dir "${tau_dir}" \
        --levels ${LEVELS}
done

# 3. Representative_value: mode + medoid を tau_dir ごとに実行
#    （integrate_complete の出力を読むためのパス対応は下流スクリプト側で行う）
echo
echo "================================================================"
echo "  STEP 3/3: Representative_value (mode_medoid per tau_dir)"
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
echo "[DONE] approach_minimum (complete-linkage): all steps finished."
