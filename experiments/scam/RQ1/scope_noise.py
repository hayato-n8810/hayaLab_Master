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
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import ijson

ROOT = Path(__file__).resolve().parents[3]
CUTOUTS = ROOT / "outputs/scam/approach/cutouts.json"
OUT_DIR = ROOT / "outputs/scam/RQ1"

DEPTHS = ["Diff", "Brother", "ExParent", "Parent"]
SIGMA_LABEL = {"Diff": "sigma1", "Brother": "sigma2", "ExParent": "sigma3", "Parent": "sigma4"}

# 句読点ノード名（named ノード集計で除外する）
PUNCT = {".", ",", ";", ":", "(", ")", "[", "]", "{", "}", '"', "'", "`"}

CSV_FIELDS = [
    "sigma",
    "depth",
    "n",
    "cut_size_median",
    "diff_size_median",
    "nondiff_ratio_all_median",
    "nondiff_ratio_named_median",
    "nondiff_ratio_named_mean",
]


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------


def compute_scope_noise(
    pairs: Iterable[dict[str, Any]],
    depths: list[str] = DEPTHS,
    punct: set[str] = PUNCT,
    log_every: int = 5000,
) -> list[dict[str, Any]]:
    """各 σ（depth）の非差分ノード比率を集計し、行リストを返す。

    Args:
        pairs: 各実装対の dict（``cutouts`` キーを持つ）の iterable。
        depths: 対象 depth の順序。
        punct: named 集計から除外する句読点ノード名集合。
        log_every: 進捗ログの頻度（0 でログ無効化）。

    Returns:
        各 depth に対応する行 dict のリスト。 キーは ``CSV_FIELDS`` と一致。
    """
    cut_sizes: dict[str, list[int]] = {d: [] for d in depths}
    diff_sizes: dict[str, list[int]] = {d: [] for d in depths}
    ratios_all: dict[str, list[float]] = {d: [] for d in depths}
    ratios_named: dict[str, list[float]] = {d: [] for d in depths}

    n = 0
    for it in pairs:
        cuts = it.get("cutouts", {})
        for depth in depths:
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
            named = [nd["origin_index"] for nd in nodes if nd.get("name") not in punct]
            if named:
                nd_non_diff = sum(1 for oi in named if oi not in diff_idx)
                ratios_named[depth].append(nd_non_diff / len(named))
        n += 1
        if log_every and n % log_every == 0:
            print(f"  scanned {n} pairs")
    if log_every:
        print(f"scanned {n} pairs total")

    rows: list[dict[str, Any]] = []
    for depth in depths:
        cs = cut_sizes[depth]
        ds = diff_sizes[depth]
        ra = ratios_all[depth]
        rn = ratios_named[depth]
        rows.append(
            {
                "sigma": SIGMA_LABEL[depth],
                "depth": depth,
                "n": len(cs),
                "cut_size_median": statistics.median(cs) if cs else 0,
                "diff_size_median": statistics.median(ds) if ds else 0,
                "nondiff_ratio_all_median": round(statistics.median(ra), 3) if ra else 0,
                "nondiff_ratio_named_median": round(statistics.median(rn), 3) if rn else 0,
                "nondiff_ratio_named_mean": round(statistics.mean(rn), 3) if rn else 0,
            }
        )
    return rows


def format_summary(rows: list[dict[str, Any]]) -> str:
    """``compute_scope_noise`` の結果を表形式テキストに整形する。"""
    lines = ["\n=== 非差分ノード比率（σ別, 全実装対で集計） ==="]
    header = f"{'sigma':6} {'n':>7} {'cut_size(med)':>14} {'diff_size(med)':>15} {'nondiff_all(med)':>17} {'nondiff_named(med)':>19} {'nondiff_named(mean)':>20}"
    lines.append(header)
    for row in rows:
        lines.append(
            f"{row['sigma']:6} {row['n']:>7} {row['cut_size_median']:>14} "
            f"{row['diff_size_median']:>15} {row['nondiff_ratio_all_median']:>17} "
            f"{row['nondiff_ratio_named_median']:>19} {row['nondiff_ratio_named_mean']:>20}"
        )
    return "\n".join(lines)


def main() -> None:
    """cutouts.json を1パス走査し，σ別の非差分ノード比率を集計する。"""
    with CUTOUTS.open("rb") as f:
        rows = compute_scope_noise(ijson.items(f, "item"))
    print(format_summary(rows))
    out = OUT_DIR / "scope_noise.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print("wrote", out)


if __name__ == "__main__":
    main()
