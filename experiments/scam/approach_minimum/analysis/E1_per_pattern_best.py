"""E1 補助: 各既知パターンごとに最適な (τ, level, depth) を求める.

E1_recall_grid.csv を読み、 パターンごとに 3 種類の指標でベストを探す:

- max_top1_f1: 最大クラスのみで F1 が最大の設定 (単一クラス集約志向)
- max_T2_f1: 集積クラス群 (∩≥2) で F1 が最大の設定 (バランス志向)
- max_all_f1: 全クラスで F1 が最大の設定 (純度重視)

出力:
    outputs/scam/approach_minimum/analysis/E1_per_pattern_best.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import KNOWN_PATTERNS, OUT_DIR, ensure_out_dir


def main() -> None:
    out_dir = ensure_out_dir()
    csv_in = out_dir / "E1_recall_grid.csv"
    with csv_in.open() as f:
        rows = list(csv.DictReader(f))

    # 各 pattern × metric_kind について最良の cell を探す
    # metric_kind: "top1_f1", "multi_T2_f1", "all_f1"
    METRICS = ["top1_f1", "multi_T2_f1", "all_f1"]

    best: dict[int, dict[str, dict]] = {}
    for pid in KNOWN_PATTERNS:
        best[pid] = {}
        pid_rows = [r for r in rows if int(r["pattern_id"]) == pid]
        for metric in METRICS:
            # 該当 metric が最大の cell を選ぶ。 tie の場合は同 metric の share/purity 両方を考慮
            ranked = sorted(
                pid_rows,
                key=lambda r: (
                    -float(r[metric]),
                    -float(r[metric.replace("_f1", "_share")]) if metric != "all_f1" else 0.0,
                    -float(r[metric.replace("_f1", "_purity")]),
                ),
            )
            top = ranked[0]
            best[pid][metric] = top

    # CSV 出力
    out_path = out_dir / "E1_per_pattern_best.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "pattern_id",
                "gp_size",
                "metric_kind",
                "best_tau",
                "best_level",
                "best_depth",
                "best_share",
                "best_purity",
                "best_f1",
                "top1_class_id",
                "top1_class_size",
                "top1_intersection",
                "n_classes",
                "n_classes_T2",
            ]
        )
        for pid in KNOWN_PATTERNS:
            for metric in METRICS:
                r = best[pid][metric]
                share_col = metric.replace("_f1", "_share")
                purity_col = metric.replace("_f1", "_purity")
                w.writerow(
                    [
                        pid,
                        r["gp_size"],
                        metric.replace("_f1", ""),
                        r["tau"],
                        r["level"],
                        r["depth"],
                        r[share_col],
                        r[purity_col],
                        r[metric],
                        r["top1_class_id"],
                        r["top1_class_size"],
                        r["top1_intersection"],
                        r["n_classes"],
                        r["n_classes_T2"],
                    ]
                )
    print(f"[OUTPUT] {out_path}")

    # stdout に整形表示
    for pid in KNOWN_PATTERNS:
        r0 = best[pid]["top1_f1"]
        print(f"\n=== pattern {pid} (正解数 {r0['gp_size']}) ===")
        for metric in METRICS:
            r = best[pid][metric]
            label = {"top1_f1": "最大クラスのみ", "multi_T2_f1": "集積クラス群", "all_f1": "全クラス"}[metric]
            share_col = metric.replace("_f1", "_share")
            purity_col = metric.replace("_f1", "_purity")
            print(
                f"  [{label:>12}] τ={r['tau']} L{r['level']} {r['depth']:>8}: "
                f"被覆率={float(r[share_col]):.3f} 純度={float(r[purity_col]):.3f} F1={float(r[metric]):.3f} "
                f"(top1 クラス={r['top1_class_id']} サイズ={r['top1_class_size']} 交差={r['top1_intersection']})"
            )


if __name__ == "__main__":
    main()
