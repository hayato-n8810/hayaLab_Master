#!/usr/bin/env bash
# jsPerf 実行時間計測の再計測ドライバ。 未完了のベンチだけを、run.sh と同じシャード構成
# (Node 16 / Playwright 8、各シャードを別々の物理コアに pin) で実行する。
#
# 本計測との違いは対象の絞り込みだけで、コア割当は run.sh の既定をそのまま使う。 再計測時の
# シャード割当は本計測の割当を引き継がず、run_measure.py が未完了ベンチを全シャードへ均等に
# 再配分するため、本計測で 1 シャードだけが残っていても全コアで分担して実行される。
#
# 既存の results.shard*.jsonl は読み取り専用で参照され、再計測分は results_retry 系列へ
# 分離出力される。 最後に merge_shards.py が result_retry.jsonl へ結合し、(slug_id, test_idx)
# 一致レコードを上書きして results.jsonl を組み立てる。
#
# 使い方 (リポジトリルートから):
#   nohup bash experiments/jsperf/measure/retry_run.sh > outputs/jsperf/measure/retry.out 2>&1 &
#   bash experiments/jsperf/measure/retry_run.sh Node              # Node だけ再計測
#   bash experiments/jsperf/measure/retry_run.sh Playwright        # Playwright だけ再計測
#   bash experiments/jsperf/measure/retry_run.sh Node Playwright   # 両方 (環境間は直列)
#   引数なしは "Node Playwright" と同じ。
#
# 環境変数:
#   REDO_STATUS  再計測対象へ含める status のカンマ区切り (例: error)。既定は空 (未計測分のみ)。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
MERGE="$HERE/merge_shards.py"

# --- 対象環境の決定 -----------------------------------------------
if [ "$#" -gt 0 ]; then
  ENVS=("$@")
else
  ENVS=(Node Playwright)
fi
for name in "${ENVS[@]}"; do
  if [ "$name" != "Node" ] && [ "$name" != "Playwright" ]; then
    echo "[retry] 不正な環境名: $name (Node または Playwright を指定してください)" >&2
    exit 1
  fi
done

# --- 再計測の引数を組み立て ---------------------------------------
MEASURE_ARGS="--resume"
if [ -n "${REDO_STATUS:-}" ]; then
  MEASURE_ARGS="$MEASURE_ARGS --redo-status $REDO_STATUS"
fi
echo "[retry] $(date -Is) 対象環境: ${ENVS[*]}  引数: $MEASURE_ARGS"

# --- 中断セッションの残骸を畳み込む -------------------------------
# per-shard の再計測結果を result_retry.jsonl へ寄せてから消す。 これをやらないと、次セッションが
# 担当ベンチを別シャードへ再配分したときに古い部分結果が新しい結果を上書きしうる。
for name in "${ENVS[@]}"; do
  ( cd "$ROOT" && uv run python "$MERGE" --env "$name" --consolidate-retry )
done

# --- 再計測の実行 (環境間は直列。run.sh がコア割当と merge を担当) ---
cd "$ROOT" || exit 1
NODE_MEASURE_ARGS="$MEASURE_ARGS" \
PW_MEASURE_ARGS="$MEASURE_ARGS" \
RUN_LOG_SUFFIX="_retry" \
  bash "$HERE/run.sh" "${ENVS[@]}"
rc=$?

echo "[retry] $(date -Is) 完了 (rc=$rc)"
for name in "${ENVS[@]}"; do
  echo "[retry] 結果: outputs/jsperf/measure/$name/{result_retry.jsonl,results.jsonl}"
done
exit "$rc"
