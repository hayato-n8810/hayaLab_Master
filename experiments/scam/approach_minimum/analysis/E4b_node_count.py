"""E4b: 孤立クラスと集約クラスの AST ノード数比較.

抽象化 abstract_level0.json と abstract_level1.json から (mb_id, depth) ごとの
AST ノード数を取り出し， 各 (τ, level, depth) セルで孤立クラスメンバと集約
クラスメンバのノード数中央値を比較する。

出力:
    outputs/scam/approach_minimum/analysis/E4b_node_count_stats.csv
    outputs/scam/approach_minimum/analysis/E4b_node_count_raw.pkl  (箱ひげ図用の生データ)
"""

from __future__ import annotations

import csv
import pickle
import sys
from pathlib import Path
from statistics import median

import ijson

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    ABSTRACT_DIR,
    DEPTHS,
    LEVELS,
    TAUS,
    ensure_out_dir,
    load_classes,
)


def load_node_counts(level: int) -> dict[str, dict[int, int]]:
    """abstract_levelN.json をストリームで読み， (mb_id, depth) ごとのノード数を返す。

    Args:
        level: 抽象化レベル (0 or 1)。

    Returns:
        ``{depth: {mb_id: node_count}}``
    """
    path = ABSTRACT_DIR / f"abstract_level{level}.json"
    counts: dict[str, dict[int, int]] = {d: {} for d in DEPTHS}
    with path.open("rb") as f:
        items = ijson.items(f, "item")
        for rec in items:
            mb_id = int(rec["id"])
            for d in DEPTHS:
                counts[d][mb_id] = len(rec["cutouts"][d]["nodes"])
    return counts


def percentile(values: list[int], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def collect_rows(level: int, raw_store: dict) -> list[dict]:
    print(f"[INFO] reading abstract_level{level}.json ...", flush=True)
    counts = load_node_counts(level)
    rows: list[dict] = []
    for tau in TAUS:
        for depth in DEPTHS:
            classes = load_classes(tau, level, depth)
            iso: list[int] = []
            clu: list[int] = []
            for cid, members in classes.items():
                is_iso = len(members) == 1
                for m in members:
                    mb_id = int(m.split("_")[0])
                    n = counts[depth].get(mb_id, 0)
                    if is_iso:
                        iso.append(n)
                    else:
                        clu.append(n)
            raw_store[(tau, level, depth, "iso")] = iso
            raw_store[(tau, level, depth, "clu")] = clu
            rows.append(
                {
                    "tau": tau,
                    "level": level,
                    "depth": depth,
                    "n_isolated": len(iso),
                    "n_clustered": len(clu),
                    "iso_node_median": percentile(iso, 0.5),
                    "iso_node_p25": percentile(iso, 0.25),
                    "iso_node_p75": percentile(iso, 0.75),
                    "iso_node_mean": (sum(iso) / len(iso)) if iso else 0.0,
                    "clu_node_median": percentile(clu, 0.5),
                    "clu_node_p25": percentile(clu, 0.25),
                    "clu_node_p75": percentile(clu, 0.75),
                    "clu_node_mean": (sum(clu) / len(clu)) if clu else 0.0,
                }
            )
    return rows


def main() -> None:
    out_dir = ensure_out_dir()
    all_rows: list[dict] = []
    raw_store: dict = {}
    for level in LEVELS:
        all_rows.extend(collect_rows(level, raw_store))

    out_csv = out_dir / "E4b_node_count_stats.csv"
    fields = list(all_rows[0].keys())
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"[OUTPUT] {out_csv}")

    raw_pkl = out_dir / "E4b_node_count_raw.pkl"
    with raw_pkl.open("wb") as f:
        pickle.dump(raw_store, f)
    print(f"[OUTPUT] {raw_pkl}")

    print("\n=== 全16セル: 孤立 vs 集約のノード数中央値 ===")
    header = f"{'τ':>3} {'L':>2} {'depth':>10} | {'iso数':>7} {'clu数':>7} | {'iso 中央':>9} {'clu 中央':>9} | {'iso 平均':>9} {'clu 平均':>9}"
    print(header)
    for r in all_rows:
        print(
            f"{r['tau']:>3.1f} {r['level']:>2} {r['depth']:>10} | "
            f"{r['n_isolated']:>7} {r['n_clustered']:>7} | "
            f"{r['iso_node_median']:>9.1f} {r['clu_node_median']:>9.1f} | "
            f"{r['iso_node_mean']:>9.1f} {r['clu_node_mean']:>9.1f}"
        )


if __name__ == "__main__":
    main()
