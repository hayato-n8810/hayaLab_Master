"""シャード分割実行の結果を結合する.

`--num-shards N` でシャード並列実行した各 `results.shard{i}.jsonl` を結合し、
(slug_id, test_idx) ソートの確定版 `results.jsonl` を書き出す。 シャードはベンチ単位で
排他分割されているため重複はなく、単純結合で全件が揃う。 各 `summary.shard{i}.json` も
status を合算して `summary.json` にまとめる。

入力: `outputs/jsperf/measure/<env>/(results.shard*.jsonl, summary.shard*.json)`
出力: `outputs/jsperf/measure/<env>/(results.jsonl, summary.json)`
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import hayalab
from hayalab.config import PathConfig

# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数・パス解決 ---
    parser = argparse.ArgumentParser(description="シャード結果 (results.shard*.jsonl) を結合する.")
    parser.add_argument("--env", choices=["Node", "Playwright"], required=True)
    args = parser.parse_args()

    CONFIG = PathConfig()
    OUT: Path = CONFIG.outputs / "jsperf" / "measure" / args.env

    # --- Section 2: シャード結果の結合 (ベンチ単位排他分割なので単純結合) ---
    shard_files = sorted(OUT.glob("results.shard*.jsonl"))
    if not shard_files:
        raise SystemExit(f"no shard results found: {OUT}/results.shard*.jsonl")
    merged: list[dict] = []
    for f in shard_files:
        merged.extend(hayalab.read_jsonl(f))
    merged.sort(key=lambda r: (r["slug_id"], r["test_idx"]))
    hayalab.write_jsonl(OUT / "results.jsonl", merged)

    # --- Section 3: summary の合算 ---
    status_counts: Counter[str] = Counter(r["status"] for r in merged)
    elapsed_max = 0.0
    for sf in sorted(OUT.glob("summary.shard*.json")):
        s = hayalab.read_json(sf)
        elapsed_max = max(elapsed_max, float(s.get("elapsed_sec", 0.0)))
    summary = {
        "env": args.env.lower(),
        "num_shards": len(shard_files),
        "wall_clock_sec": elapsed_max,  # 並列実行のため最も遅いシャードの経過時間
        "total_tests": len(merged),
        "status_counts": {k: status_counts.get(k, 0) for k in ("success", "error", "timeout")},
    }
    hayalab.write_json(OUT / "summary.json", summary)

    # --- Section 4: 進捗レポート ---
    print(f"[merge] {args.env}: merged {len(shard_files)} shards -> {len(merged)} tests")
    print(f"[merge] status_counts: {summary['status_counts']}")
    print(f"[merge] outputs: {OUT / 'results.jsonl'}")
