"""計測結果から実行時間に差のあるプログラムペアを作成する.

`outputs/jsperf/measure/<env>/results.jsonl` の success レコードについて、
test ごとに samples_ns の平均の信頼区間を算出し、同一 slug_id 内で信頼区間が
一切重複しない test の組をペアとして書き出す。

入力: `outputs/jsperf/measure/<env>/results.jsonl`
出力: `outputs/jsperf/pair/time/<env>/`
- `intervals.jsonl` : test ごとの (平均, 信頼区間) (slug_id, test_idx) ソート
- `pairs.jsonl`     : 信頼区間が重複しない test ペア (slug_id, fast_test_idx, slow_test_idx) ソート
- `summary.json`    : 対象ベンチマーク / test 数とペア数の集計
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import hayalab
from hayalab.config import PathConfig
from hayalab.config.jsperf_config import CONFIDENCE
from hayalab.jsperf.interval import disjoint_interval_pairs, mean_confidence_interval

# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数・パス解決 ---
    parser = argparse.ArgumentParser(description="信頼区間が重複しない実行時間ペアを作成する.")
    parser.add_argument("--env", choices=["Node", "Playwright"], default="Node")
    args = parser.parse_args()

    CONFIG = PathConfig()
    results_path: Path = CONFIG.outputs / "jsperf" / "measure" / args.env / "results.jsonl"
    out_dir: Path = CONFIG.outputs / "jsperf" / "pair" / "time" / args.env
    if not results_path.exists():
        raise SystemExit(f"results not found: {results_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: success レコードの信頼区間算出 ---
    records = hayalab.read_jsonl(results_path)
    intervals: list[dict] = []
    for record in records:
        samples = record.get("samples_ns") or []
        if record.get("status") != "success" or len(samples) < 2:
            continue
        mean, ci_low, ci_high = mean_confidence_interval(samples, CONFIDENCE)
        intervals.append(
            {
                "slug_id": record["slug_id"],
                "test_idx": record["test_idx"],
                "n": len(samples),
                "mean_ns": mean,
                "ci_low_ns": ci_low,
                "ci_high_ns": ci_high,
            }
        )
    intervals.sort(key=lambda r: (r["slug_id"], r["test_idx"]))
    hayalab.write_jsonl(out_dir / "intervals.jsonl", intervals)

    # --- Section 3: slug_id 単位で信頼区間が重複しない組を抽出 ---
    by_slug: dict[str, dict[int, dict]] = defaultdict(dict)
    for stat in intervals:
        by_slug[stat["slug_id"]][stat["test_idx"]] = stat

    pairs: list[dict] = []
    target_slugs = 0  # 信頼区間を算出できた test が 2 つ以上あるベンチマーク数
    target_tests = 0  # 上記ベンチマークに属する test 数
    total_pairs = 0  # 上記ベンチマーク内で組める test ペアの総数
    for slug_id in sorted(by_slug):
        stats_by_test = by_slug[slug_id]
        if len(stats_by_test) < 2:
            continue
        target_slugs += 1
        target_tests += len(stats_by_test)
        total_pairs += len(stats_by_test) * (len(stats_by_test) - 1) // 2
        bounds = {idx: (s["ci_low_ns"], s["ci_high_ns"]) for idx, s in stats_by_test.items()}
        for fast_idx, slow_idx in disjoint_interval_pairs(bounds):
            fast, slow = stats_by_test[fast_idx], stats_by_test[slow_idx]
            pairs.append(
                {
                    "slug_id": slug_id,
                    "fast_test_idx": fast_idx,
                    "slow_test_idx": slow_idx,
                    "fast": {"n": fast["n"], "mean_ns": fast["mean_ns"]},
                    "slow": {"n": slow["n"], "mean_ns": slow["mean_ns"]},
                    "mean_ratio": slow["mean_ns"] / fast["mean_ns"],  # slowがfastの何倍遅いか
                }
            )
    pairs.sort(key=lambda p: (p["slug_id"], p["fast_test_idx"], p["slow_test_idx"]))
    hayalab.write_jsonl(out_dir / "pairs.jsonl", pairs)

    # --- Section 4: 集計の保存 ---
    summary = {
        "env": args.env,
        "confidence": CONFIDENCE,  # 信頼区間の信頼水準
        "total_slugs": len({r["slug_id"] for r in records}),  # 計測結果に含まれる全ベンチマーク数
        "total_tests": len(records),  # 計測結果に含まれる全 test 数
        "target_slugs": target_slugs,  # 比較対象となったベンチマーク数
        "target_tests": target_tests,  # 比較対象となった test 数
        "total_pairs": total_pairs,  # 比較対象ベンチマーク内で組める全 test ペア数
        "disjoint_pairs": len(pairs),  # 信頼区間が一切重複しない test ペア数
    }
    hayalab.write_json(out_dir / "summary.json", summary)
    print(f"[pair] {args.env}: slugs={target_slugs}/{summary['total_slugs']} tests={target_tests}/{len(records)} pairs={len(pairs)}/{total_pairs} -> {out_dir}")
