#!/usr/bin/env bash
# jsPerf 実行時間計測ドライバ (本計測 + 再計測)。
# Node -> Playwright の順に (環境間は直列で)、各環境内は複数シャード (Node 16 / Playwright 8) を
# 別々の物理コアに pin した Docker コンテナで擬似並列に計測する。同一ベンチ (ペア) は同一シャード
# に割り当てられるため、ペア内の相対比較の妥当性は保たれる。結果の結合は merge_shards.py で行う。
#
# 使い方:
#   bash run.sh                                # 本計測 -> 再計測 (Node, Playwright 両方)
#   bash run.sh Node                           # 指定環境のみ 本計測 -> 再計測 (複数指定可)
#   bash run.sh --resume                       # 再計測のみ (本計測はスキップ)
#   bash run.sh --resume --redo-status error   # 再計測のみ + error レコードも再計測対象にする
#   bash run.sh --resume Playwright            # Playwright だけ再計測のみ
#   bash run.sh --redo-status error            # 本計測 -> 再計測。再計測で error も対象にする
#
# 各環境は「本計測フェーズ」と「再計測フェーズ」からなる:
#   - 本計測フェーズ (--resume 指定時はスキップ): 全ベンチを計測し results.shard*.jsonl を出力。
#   - 再計測フェーズ (常に実行): 既存 results を読み取り専用で参照し、未完了ベンチ (本計測の
#     取りこぼし。--redo-status 指定時はその status も) だけを全シャードへ再配分して計測し、
#     results_retry 系列へ分離出力する (本計測の原本を保全)。開始前に中断セッションの残骸を
#     merge_shards.py --consolidate-retry で result_retry.jsonl へ畳み込む。
# 本計測が全完走していれば再計測フェーズは対象ゼロで即終了する (取りこぼし時の保険)。
# ログは本計測が run.log、再計測が run_retry.log。
#
# 計測後の結合 (results_retry を本計測へ上書き適用して確定版 results.jsonl を作る) は別途:
#   uv run python experiments/jsperf/measure/merge_shards.py --env <Node|Playwright>
#
# コア割当は各 docker-compose.yml のデフォルト (この機の NUMA/物理コアに合わせ済み) を使う。
# 別ホストでは NODE_SHARD*_CPUS / PW_SHARD*_CPUS で上書き。メモリは 180GiB と潤沢なため無制限。
#
# 進捗の確認方法 (実行中): 別ターミナルで各シャードの完了件数を数える:
#   wc -l outputs/jsperf/measure/Node/results*.shard*.jsonl
#   wc -l outputs/jsperf/measure/Playwright/results*.shard*.jsonl
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
MERGE="$HERE/merge_shards.py"

# --- 引数パース (フラグ + 対象環境) ---
RESUME_ONLY=0
REDO_STATUS="${REDO_STATUS:-}"   # 環境変数でも指定可。--redo-status が優先
ENVS=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --resume) RESUME_ONLY=1 ;;
    --redo-status) shift; REDO_STATUS="${1:-}" ;;
    Node | Playwright) ENVS="$ENVS $1" ;;
    *) echo "[run] 不明な引数: $1 (使い方はスクリプト冒頭のコメント参照)" >&2; exit 1 ;;
  esac
  shift
done
[ -z "$ENVS" ] && ENVS="Node Playwright"

# --- 再計測フェーズの run_measure.py 追加引数 ---
RETRY_ARGS="--resume"
[ -n "$REDO_STATUS" ] && RETRY_ARGS="$RETRY_ARGS --redo-status $REDO_STATUS"

# 1 フェーズ分の docker compose up (環境変数で run_measure.py へ追加引数を渡す)
# $1 name, $2 compose, $3 outdir, $4 measure_args, $5 log_suffix
_up () {
  case "$1" in
    Node) NODE_MEASURE_ARGS="$4" docker compose -f "$2" up 2>&1 | tee "$3/run$5.log" ;;
    Playwright) PW_MEASURE_ARGS="$4" docker compose -f "$2" up 2>&1 | tee "$3/run$5.log" ;;
  esac
  docker compose -f "$2" down
}

run_env () {
  name="$1"                              # Node / Playwright
  compose="$HERE/$name/docker-compose.yml"
  input="$ROOT/data/jsPerf/$name/measure"
  outdir="$ROOT/outputs/jsperf/measure/$name"

  if [ ! -d "$input" ] || [ -z "$(ls -A "$input" 2>/dev/null)" ]; then
    echo "[run] SKIP $name: 入力がありません ($input)。step6 を先に実行してください。"
    return
  fi
  mkdir -p "$outdir"

  echo "[run] === $name: イメージビルド ==="
  docker compose -f "$compose" build

  # --- 本計測フェーズ (--resume 指定時はスキップ) ---
  if [ "$RESUME_ONLY" = "0" ]; then
    echo "[run] === $name: 本計測 (擬似並列)。進捗は $outdir/results.shard*.jsonl の行数で確認できます ==="
    _up "$name" "$compose" "$outdir" "" ""
  fi

  # --- 再計測フェーズ (常に実行。本計測の取りこぼし + --redo-status 指定分を救済) ---
  echo "[run] === $name: 再計測の前処理 (consolidate-retry) ==="
  ( cd "$ROOT" && uv run python "$MERGE" --env "$name" --consolidate-retry )
  echo "[run] === $name: 再計測 ($RETRY_ARGS)。進捗は $outdir/results_retry.shard*.jsonl の行数で確認できます ==="
  _up "$name" "$compose" "$outdir" "$RETRY_ARGS" "_retry"

  echo "[run] === $name: 完了 (結合は merge_shards.py --env $name で) ==="
}

# 環境間は直列に実行する (ホスト全体でコア競合を避けるため同時起動しない)
for name in $ENVS; do
  run_env "$name"
done
echo "[run] 全計測完了 ($ENVS )  結合: uv run python $MERGE --env <Node|Playwright>"
