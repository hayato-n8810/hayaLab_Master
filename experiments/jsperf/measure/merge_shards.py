"""シャード分割実行の結果を結合する.

`--num-shards N` でシャード並列実行した各 `results.shard{i}.jsonl` を結合し、
(slug_id, test_idx) ソートの確定版 `results.jsonl` を書き出す。 シャードはベンチ単位で
排他分割されているため重複はなく、単純結合で全件が揃う。 各 `summary.shard{i}.json` も
status を合算して `summary.json` にまとめる。

`--resume` 実行で `results_retry.shard{i}.jsonl` があれば、それらを結合した `result_retry.jsonl`
を中間成果物として書き出し、(slug_id, test_idx) が一致する本計測レコードを再計測レコードで
置き換えてから `results.jsonl` を組み立てる。 本計測のシャード成果物は読むだけなので、この
スクリプトは何度実行しても同じ `results.jsonl` になる。
適用順は 本計測シャード → `result_retry.jsonl` (過去セッション) → `results_retry.shard*.jsonl`
(最新セッション) で、後のものが勝つ。

`--consolidate-retry` は再計測セッションの開始前に使う。 中断で残った
`results_retry.shard*.jsonl` を `result_retry.jsonl` へ畳み込んで per-shard 側を削除するため、
次セッションが担当ベンチを別シャードへ再配分しても、古い部分結果が新しい結果を上書きしない。

入力: `outputs/jsperf/measure/<env>/`
- `results.shard*.jsonl`, `summary.shard*.json` (本計測)
- `results_retry.shard*.jsonl`, `summary_retry.shard*.json` (再計測。あれば)
- `result_retry.jsonl` (過去の再計測セッションを畳み込んだもの。あれば)

出力: `outputs/jsperf/measure/<env>/(result_retry.jsonl, results.jsonl, summary.json)`
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
    parser.add_argument("--consolidate-retry", action="store_true", help="再計測セッション開始前に results_retry.shard* を result_retry.jsonl へ畳み込む")
    args = parser.parse_args()

    CONFIG = PathConfig()
    OUT: Path = CONFIG.outputs / "jsperf" / "measure" / args.env
    retry_path = OUT / "result_retry.jsonl"

    # --- Section 2: 再計測セッションの前処理 (--consolidate-retry) ---
    if args.consolidate_retry:
        stale = sorted(OUT.glob("results_retry.shard*.jsonl"))
        if not stale:
            print(f"[merge] {args.env}: 畳み込み対象なし (results_retry.shard*.jsonl は存在しません)")
            raise SystemExit(0)
        folded: dict[tuple[str, int], dict] = {}
        for f in (retry_path, *stale):  # 中断セッションの結果が過去分より優先される
            if f.exists():
                folded.update({(r["slug_id"], r["test_idx"]): r for r in hayalab.read_jsonl(f)})
        hayalab.write_jsonl(retry_path, sorted(folded.values(), key=lambda r: (r["slug_id"], r["test_idx"])))
        for f in stale:
            f.unlink()
        print(f"[merge] {args.env}: consolidated {len(stale)} retry shards -> {len(folded)} tests ({retry_path})")
        raise SystemExit(0)

    # --- Section 3: シャード結果の結合 (ベンチ単位排他分割なので単純結合) ---
    shard_files = sorted(OUT.glob("results.shard*.jsonl"))
    if not shard_files:
        raise SystemExit(f"no shard results found: {OUT}/results.shard*.jsonl")
    merged: list[dict] = []
    for f in shard_files:
        merged.extend(hayalab.read_jsonl(f))

    # --- Section 4: 再計測結果の結合と上書き適用 ---
    # 適用順は 本計測 → result_retry.jsonl (過去セッション) → results_retry.shard* (最新セッション)
    retry_files = sorted(OUT.glob("results_retry.shard*.jsonl"))
    retry: dict[tuple[str, int], dict] = {}
    for f in (retry_path, *retry_files):
        if f.exists():
            retry.update({(r["slug_id"], r["test_idx"]): r for r in hayalab.read_jsonl(f)})
    if retry:
        hayalab.write_jsonl(retry_path, sorted(retry.values(), key=lambda r: (r["slug_id"], r["test_idx"])))
        by_key = {(r["slug_id"], r["test_idx"]): r for r in merged}
        by_key.update(retry)
        merged = list(by_key.values())

    merged.sort(key=lambda r: (r["slug_id"], r["test_idx"]))
    hayalab.write_jsonl(OUT / "results.jsonl", merged)

    # --- Section 5: summary の合算 ---
    status_counts: Counter[str] = Counter(r["status"] for r in merged)
    elapsed_max = 0.0
    for pattern in ("summary.shard*.json", "summary_retry.shard*.json"):
        for sf in sorted(OUT.glob(pattern)):
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

    # --- Section 6: 進捗レポート ---
    print(f"[merge] {args.env}: merged {len(shard_files)} shards -> {len(merged)} tests")
    if retry:
        print(f"[merge] retry: {len(retry_files)} shards -> {len(retry)} tests ({retry_path})")
    print(f"[merge] status_counts: {summary['status_counts']}")
    print(f"[merge] outputs: {OUT / 'results.jsonl'}")
