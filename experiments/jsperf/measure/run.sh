#!/usr/bin/env bash
# jsPerf 実行時間計測を Node -> Playwright の順に直列実行する。
# 各環境は最小マウントの Docker (run --rm の使い捨てコンテナ) で走り、
# 計測は環境内でも直列 (run_measure.py が 1 件ずつ node / Chromium を回す)。
#
# 進捗の確認方法 (実行中):
#   - 本スクリプトの標準出力 / 各 run.log に 100 件ごとの進捗が出る
#   - 別ターミナルで完了件数を数える:
#       wc -l outputs/jsperf/measure/Node/results.jsonl
#       wc -l outputs/jsperf/measure/Playwright/results.jsonl
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"

run_env () {
  local name="$1"                     # Node / Playwright
  local service="$2"                  # bench-node / bench-playwright
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

  echo "[run] === $name: 計測開始 (直列)。進捗は下記ログと $outdir/results.jsonl の行数で確認できます ==="
  docker compose -f "$compose" run --rm "$service" \
    uv run python "experiments/jsperf/measure/$name/run_measure.py" 2>&1 | tee "$outdir/run.log"

  echo "[run] === $name: 完了 (結果: $outdir) ==="
}

# 計測は 1 環境ずつ直列に実行する (ホスト全体でコア競合を避けるため同時起動しない)
run_env Node bench-node
run_env Playwright bench-playwright

echo "[run] 全計測完了。結果: $ROOT/outputs/jsperf/measure/{Node,Playwright}/"
