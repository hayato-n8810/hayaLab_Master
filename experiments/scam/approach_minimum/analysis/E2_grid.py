"""E2: 集約結果の全体統計グリッド (τ × level × depth = 32 cell).

各セルで以下を計算:

- num_classes: クラス総数
- num_patterns: 29,809 (全 cutout 数)
- n_isolated: 1 メンバのみのクラス数
- isolated_ratio: n_isolated / num_patterns
- max_class_size: 最大クラスのメンバ数
- max_share: max_class_size / num_patterns (最大クラスが占める割合)
- aggregation_ratio: (num_patterns - n_isolated) / num_patterns (集約が発生している実装対の割合)
- median_size_no_isolated: 孤立クラス除く中央値
- mean_size_no_isolated: 孤立クラス除く平均
- n_ge10: メンバ ≥ 10 のクラス数
- n_ge100: メンバ ≥ 100 のクラス数

出力:
    outputs/scam/approach_minimum/analysis/E2_grid.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))
from _common import DEPTHS, LEVELS, TAUS, ensure_out_dir, load_classes, load_meta


def compute_cell(tau: float, level: int, depth: str) -> dict:
    classes = load_classes(tau, level, depth)
    meta = load_meta(tau, level, depth)
    # 一つのクラスに含まれるメンバーの数のリスト
    sizes = [len(m) for m in classes.values()]
    # クラスの合計数
    num_classes = len(sizes)
    # 全事例数（データセットから利用した実装（対）の数）
    num_patterns_total = meta.get("num_bigram_patterns", 0) + meta.get("num_unigram_patterns", 0) + meta.get("num_excluded_empty", 0)
    # クラス内に含まれる（除外されていない）事例の合計 (= num_bigram_patterns + num_unigram_patterns、 excluded は含まれない)
    num_patterns_in_classes = sum(sizes)
    isolated = [s for s in sizes if s == 1]
    non_isolated = [s for s in sizes if s > 1]
    n_isolated = len(isolated)
    max_sz = max(sizes) if sizes else 0

    # M2 (bigram) / U1 (unigram) 内訳
    n_M2 = sum(1 for cid in classes if "_M2_" in cid)
    n_U1 = sum(1 for cid in classes if "_U1_" in cid)

    return {
        "tau": tau,
        "level": level,
        "depth": depth,
        "num_classes": num_classes,
        "num_bigram_classes": n_M2,
        "num_unigram_classes": n_U1,
        "num_bigram_patterns": meta.get("num_bigram_patterns", 0),
        "num_unigram_patterns": meta.get("num_unigram_patterns", 0),
        "num_excluded_empty": meta.get("num_excluded_empty", 0),
        "num_patterns_in_classes": num_patterns_in_classes,
        "num_patterns_total": num_patterns_total,
        "n_isolated": n_isolated,
        "isolated_ratio": n_isolated / num_patterns_in_classes if num_patterns_in_classes else 0.0,
        "max_class_size": max_sz,
        "max_share": max_sz / num_patterns_in_classes if num_patterns_in_classes else 0.0,
        "aggregation_ratio": (num_patterns_in_classes - n_isolated) / num_patterns_in_classes if num_patterns_in_classes else 0.0,
        "median_size_no_isolated": median(non_isolated) if non_isolated else 0,
        "mean_size_no_isolated": (sum(non_isolated) / len(non_isolated)) if non_isolated else 0.0,
        "n_ge10": sum(1 for s in sizes if s >= 10),
        "n_ge100": sum(1 for s in sizes if s >= 100),
    }


def main() -> None:
    out_dir = ensure_out_dir()
    rows: list[dict] = []
    for tau in TAUS:
        for level in LEVELS:
            for depth in DEPTHS:
                rows.append(compute_cell(tau, level, depth))

    fields = list(rows[0].keys())
    csv_path = out_dir / "E2_grid.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[OUTPUT] {csv_path}")

    # stdout 整形表示
    print(f"\n{'τ':>3} {'L':>2} {'depth':>10} | {'num_cls':>7} {'iso%':>6} {'max':>6} {'max%':>5} {'agg%':>5} {'med':>4} {'≥10':>4} {'≥100':>4}")
    for r in rows:
        print(
            f"{r['tau']:>3.1f} {r['level']:>2} {r['depth']:>10} | "
            f"{r['num_classes']:>7} "
            f"{r['isolated_ratio'] * 100:>5.1f}% "
            f"{r['max_class_size']:>6} "
            f"{r['max_share'] * 100:>4.1f}% "
            f"{r['aggregation_ratio'] * 100:>4.1f}% "
            f"{r['median_size_no_isolated']:>4.0f} "
            f"{r['n_ge10']:>4} "
            f"{r['n_ge100']:>4}"
        )


if __name__ == "__main__":
    main()
