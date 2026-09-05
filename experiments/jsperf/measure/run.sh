#!/usr/bin/env bash
# jsPerf 実行時間計測を Node -> Playwright の順に (環境間は直列で) 実行する。
# 各環境内では複数シャード (Node 16 / Playwright 8) を別々の物理コアに pin した Docker
# コンテナで擬似並列に計測し、完了後に merge_shards.py で results.jsonl に結合する。
# 同一ベンチ (ペア) は同一シャードに割り当てられるため、ペア内の相対比較の妥当性は保たれる。
# コア割当は各 docker-compose.yml のデフォルト (この機の NUMA/物理コアに合わせ済み) を使う。
# 別ホストでは NODE_SHARD*_CPUS / PW_SHARD*_CPUS で上書き。メモリは 180GiB と潤沢なため無制限。
#
# 使い方:
#   bash run.sh              # Node -> Playwright を直列で実行
#   bash run.sh Node         # 指定した環境のみ実行 (複数指定可)
# 環境変数:
#   NODE_MEASURE_ARGS  Node の run_measure.py へ渡す追加引数 (例: --resume)
#   RUN_LOG_SUFFIX     run.log のファイル名サフィックス (既存ログを上書きしたくないとき)
#
# 進捗の確認方法 (実行中):
#   - docker compose up が全シャードのログを流す
#   - 別ターミナルで各シャードの完了件数を数える:
#       wc -l outputs/jsperf/measure/Node/results.shard*.jsonl
#       wc -l outputs/jsperf/measure/Playwright/results.shard*.jsonl
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

run_env () {
  local name="$1"                     # Node / Playwright
  local compose="$HERE/$name/docker-compose.yml"
  local input="$ROOT/data/jsPerf/$name/measure"
  local outdir="$ROOT/outputs/jsperf/measure/$name"

  if [ ! -d "$input" ] || [ -z "$(ls -A "$input" 2>/dev/null)" ]; then
    echo "[run] SKIP $name: 入力がありません ($input)。step6 を先に実行してください。"
    return
  fi
  mkdir -p "$outdir"

  echo "[run] === $name: イメージビルド ==="
  docker compose -f "$compose" build

  echo "[run] === $name: 計測開始 (4 シャード擬似並列)。進捗は $outdir/results.shard*.jsonl の行数で確認できます ==="
  # 全シャードを並列起動し、全コンテナ終了まで待つ (アタッチモード)
  docker compose -f "$compose" up 2>&1 | tee "$outdir/run${RUN_LOG_SUFFIX:-}.log"
  docker compose -f "$compose" down

  # echo "[run] === $name: シャード結果を結合 ==="
  # uv run python "$HERE/merge_shards.py" --env "$name"

  echo "[run] === $name: 完了 (結果: $outdir/results.jsonl) ==="
}

# 引数で環境を指定した場合はその環境だけを実行する (再計測でどちらか一方だけ動かす用途)。
# 引数なしのときは環境間を直列で実行する (ホスト全体でコア競合を避けるため同時起動しない)。
if [ "$#" -gt 0 ]; then
  for name in "$@"; do
    run_env "$name"
  done
  echo "[run] 計測完了 ($*)"
else
  run_env Node
  run_env Playwright
  echo "[run] 全計測完了。結果: $ROOT/outputs/jsperf/measure/{Node,Playwright}/results.jsonl"
fi
