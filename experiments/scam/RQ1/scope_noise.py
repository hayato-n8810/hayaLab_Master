r"""スコープ拡大に伴う「非本質ノードの混入」を定量化する。

サイズ設計（σ）を広げると，差分ノードに加えて周辺の文脈ノードが切り出しコード片に
取り込まれる。本スクリプトは，各 σ について，切り出しコード片に含まれるノードのうち
差分ノードに由来しないノードの割合（非差分ノード比率）を集計する。

定義（各実装対・各 σ の切り出しコード片について）:
  非差分ノード比率 = (|切り出しノード| - |切り出しノード ∩ 差分ノード|) / |切り出しノード|

ここで差分ノードは cut の ``diff_node_indices``，切り出しノードは ``nodes`` の
``origin_index`` 集合である。句読点ノードを除いた named ノードのみで集計した値も併せて
報告する（代表値のトークンは句読点を含まないため）。

入力: outputs/scam/approach/cutouts.json（1 パス走査）
出力: scope_noise.csv（σ 別の集計），標準出力に要約表
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

import ijson

ROOT = Path(__file__).resolve().parents[3]
CUTOUTS = ROOT / "outputs/scam/approach/cutouts.json"
OUT_DIR = ROOT / "outputs/scam/RQ1/complete_all_tau"

DEPTHS = ["Diff", "Brother", "ExParent", "Parent"]
SIGMA_LABEL = {"Diff": "sigma1", "Brother": "sigma2", "ExParent": "sigma3", "Parent": "sigma4"}

# 句読点ノード名（named ノード集計で除外する）
PUNCT = {".", ",", ";", ":", "(", ")", "[", "]", "{", "}", '"', "'", "`"}


def main() -> None:
    """cutouts.json を1パス走査し，σ別の非差分ノード比率を集計する。"""
    # depth -> list of metrics
    cut_sizes: dict[str, list[int]] = {d: [] for d in DEPTHS}
    diff_sizes: dict[str, list[int]] = {d: [] for d in DEPTHS}
    ratios_all: dict[str, list[float]] = {d: [] for d in DEPTHS}
    ratios_named: dict[str, list[float]] = {d: [] for d in DEPTHS}

    n = 0
    with CUTOUTS.open("rb") as f:
        for it in ijson.items(f, "item"):
            cuts = it.get("cutouts", {})
            for depth in DEPTHS:
                cut = cuts.get(depth)
                if not cut:
                    continue
                nodes = cut.get("nodes", [])
                if not nodes:
                    continue
                diff_idx = set(cut.get("diff_node_indices", []))

                # 全ノード基準
                origin = [nd["origin_index"] for nd in nodes]
                total = len(origin)
                non_diff = sum(1 for oi in origin if oi not in diff_idx)
                cut_sizes[depth].append(total)
                diff_sizes[depth].append(len(diff_idx))
                ratios_all[depth].append(non_diff / total)

                # named ノード基準（句読点を除外）
                named = [nd["origin_index"] for nd in nodes if nd.get("name") not in PUNCT]
                if named:
                    nd_non_diff = sum(1 for oi in named if oi not in diff_idx)
                    ratios_named[depth].append(nd_non_diff / len(named))
            n += 1
            if n % 5000 == 0:
                print(f"  scanned {n} pairs")
    print(f"scanned {n} pairs total")

    rows = []
    print("\n=== 非差分ノード比率（σ別, 全実装対で集計） ===")
    print(f"{'sigma':6} {'n':>7} {'cut_size(med)':>14} {'diff_size(med)':>15} {'nondiff_all(med)':>17} {'nondiff_named(med)':>19} {'nondiff_named(mean)':>20}")
    for depth in DEPTHS:
        cs = cut_sizes[depth]
        ds = diff_sizes[depth]
        ra = ratios_all[depth]
        rn = ratios_named[depth]
        row = {
            "sigma": SIGMA_LABEL[depth],
            "depth": depth,
            "n": len(cs),
            "cut_size_median": statistics.median(cs) if cs else 0,
            "diff_size_median": statistics.median(ds) if ds else 0,
            "nondiff_ratio_all_median": round(statistics.median(ra), 3) if ra else 0,
            "nondiff_ratio_named_median": round(statistics.median(rn), 3) if rn else 0,
            "nondiff_ratio_named_mean": round(statistics.mean(rn), 3) if rn else 0,
        }
        rows.append(row)
        print(
            f"{row['sigma']:6} {row['n']:>7} {row['cut_size_median']:>14} "
            f"{row['diff_size_median']:>15} {row['nondiff_ratio_all_median']:>17} "
            f"{row['nondiff_ratio_named_median']:>19} {row['nondiff_ratio_named_mean']:>20}"
        )

    out = OUT_DIR / "scope_noise.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "sigma",
                "depth",
                "n",
                "cut_size_median",
                "diff_size_median",
                "nondiff_ratio_all_median",
                "nondiff_ratio_named_median",
                "nondiff_ratio_named_mean",
            ],
        )
        w.writeheader()
        w.writerows(rows)
    print("wrote", out)


if __name__ == "__main__":
    main()
