#!/bin/sh
# scan_jsperf 実行パイプライン
# get_html → get_benchmark
#
# 出力先:
#   get_html:      outputs/scan_jsperf/index.json
#                  outputs/scan_jsperf/html/<slug>_r<N>.html
#   get_benchmark: outputs/scan_jsperf/benchmarks.json
#                  outputs/scan_jsperf/extraction_errors.jsonl (失敗があれば)
#
# 実行例（デフォルト並列数）:
#   sh   experiments/scan_jsperf/run.sh
#   bash experiments/scan_jsperf/run.sh
#
# 並列数を変える場合（WORKERS は get_benchmark.py の --workers に渡す）:
#   WORKERS=8 bash experiments/scan_jsperf/run.sh
#
# 取得件数・スリープ間隔は get_html.py 冒頭の FETCH_LIMIT / SLEEP_SECONDS で
# 直接調整する（CLI 引数ではない）．本番運用時は FETCH_LIMIT=None に変更．

# 2026/06/16時点の収集
set -eu

# 1. get_html: サイトマップから HTML を順次取得
echo
echo "================================================================"
echo "  STEP 1/2: get_html.py"
echo "================================================================"
python3 experiments/scan_jsperf/get_html.py

# 2. get_benchmark: 取得済み HTML から benchmark 情報を抽出（並列）
echo
echo "================================================================"
echo "  STEP 2/2: get_benchmark.py --workers 30"
echo "================================================================"
python3 experiments/scan_jsperf/get_benchmark.py --workers 30

echo
echo "[DONE] scan_jsperf: all steps finished."
