"""E3: 各事例の最小集約サイズ分布.

各実装対 mb_id について、 サイズ depth を Diff → Brother → ExParent → Parent の順に
広げていき、 ``クラスサイズ ≥ 2`` を満たす最初の depth を 「最小集約サイズ」 とする。
全 depth で isolated であれば "none"。

(τ, 抽象化レベル) ペアごとに、 分布 {Diff, Brother, ExParent, Parent, none} を集計する。

出力:
    outputs/scam/approach_minimum/analysis/E3_min_size_distribution.csv
    outputs/scam/approach_minimum/analysis/E3_min_size_per_mb.csv
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import DEPTHS, LEVELS, TAUS, build_member_to_class, ensure_out_dir, load_classes

# 判定順序 (paper §4.1 のサイズ設計の包含順序 σ1 ⊂ σ2 ⊂ σ3 ⊂ σ4 と一致)
SIZE_ORDER: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")
NONE_LABEL = "none"
EXCLUDED_LABEL = "excluded"


def build_mb_to_class_size(tau: float, level: int) -> dict[str, dict[int, int]]:
    """各 depth ごとに ``{mb_id: class_size}`` 索引を作る。

    v7: integrate.py の三本立て化により、 excluded (空 cutout) の mb_id は
    どの depth でも classes に居ない。 こうした mb_id は ``EXCLUDED_LABEL`` に分類する。
    """
    out: dict[str, dict[int, int]] = {}
    for depth in SIZE_ORDER:
        classes = load_classes(tau, level, depth)
        class_size = {cid: len(m) for cid, m in classes.items()}
        m2c = build_member_to_class(classes, depth)
        out[depth] = {mb_id: class_size[cid] for mb_id, cid in m2c.items()}
    return out


def compute_min_size(mb_id: int, mb_to_size_by_depth: dict[str, dict[int, int]]) -> str:
    """``mb_id`` について最小集約サイズを返す。

    優先順位:
    - 任意の depth でクラスサイズ ≥ 2 になる最初の depth を返す
    - どの depth でもクラスに居なければ EXCLUDED (cutout が空)
    - どの depth でもサイズ 1 (singleton) なら NONE
    """
    # まず、 任意の depth でクラスに居るか確認
    found_anywhere = any(mb_id in mb_to_size_by_depth[d] for d in SIZE_ORDER)
    if not found_anywhere:
        return EXCLUDED_LABEL
    for depth in SIZE_ORDER:
        size = mb_to_size_by_depth[depth].get(mb_id, 1)
        if size >= 2:
            return depth
    return NONE_LABEL


def compute_pair(tau: float, level: int) -> tuple[Counter, list[dict]]:
    """1 (τ, level) ペアの集計を返す。"""
    mb_to_size_by_depth = build_mb_to_class_size(tau, level)
    # 全 mb_id 集合 (各 depth で 29,809 から excluded を引いた数。 集約結果に
    # 現れる mb_id の union を取れば集約対象事例 + excluded 候補が揃わない可能性が
    # あるため、 mb_id を 0-29808 で固定して全件をカバーする)
    mb_ids = set(range(29809))

    counter: Counter = Counter()
    per_mb_rows: list[dict] = []
    for mb_id in sorted(mb_ids):
        ms = compute_min_size(mb_id, mb_to_size_by_depth)
        counter[ms] += 1
        per_mb_rows.append(
            {
                "tau": tau,
                "level": level,
                "mb_id": mb_id,
                "min_effective_size": ms,
                "size_Diff": mb_to_size_by_depth["Diff"].get(mb_id, 1),
                "size_Brother": mb_to_size_by_depth["Brother"].get(mb_id, 1),
                "size_ExParent": mb_to_size_by_depth["ExParent"].get(mb_id, 1),
                "size_Parent": mb_to_size_by_depth["Parent"].get(mb_id, 1),
            }
        )
    return counter, per_mb_rows


def main() -> None:
    out_dir = ensure_out_dir()

    distribution_rows: list[dict] = []
    per_mb_all: list[dict] = []

    for tau in TAUS:
        for level in LEVELS:
            counter, per_mb_rows = compute_pair(tau, level)
            total = sum(counter.values())
            row = {"tau": tau, "level": level, "n_mb": total}
            for label in (*SIZE_ORDER, NONE_LABEL, EXCLUDED_LABEL):
                row[f"count_{label}"] = counter[label]
                row[f"ratio_{label}"] = counter[label] / total if total else 0.0
            distribution_rows.append(row)
            per_mb_all.extend(per_mb_rows)
            print(
                f"[τ={tau} L{level}] " + " | ".join(f"{label}: {counter[label]} ({counter[label] / total * 100:.1f}%)" for label in (*SIZE_ORDER, NONE_LABEL, EXCLUDED_LABEL)) + f" (total {total})",
                flush=True,
            )

    # 分布 CSV
    dist_path = out_dir / "E3_min_size_distribution.csv"
    fields = ["tau", "level", "n_mb"]
    for label in (*SIZE_ORDER, NONE_LABEL, EXCLUDED_LABEL):
        fields.append(f"count_{label}")
        fields.append(f"ratio_{label}")
    with dist_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in distribution_rows:
            w.writerow(r)
    print(f"\n[OUTPUT] {dist_path}")

    # per-mb CSV
    per_mb_path = out_dir / "E3_min_size_per_mb.csv"
    fields_pm = ["tau", "level", "mb_id", "min_effective_size", "size_Diff", "size_Brother", "size_ExParent", "size_Parent"]
    with per_mb_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields_pm)
        w.writeheader()
        for r in per_mb_all:
            w.writerow(r)
    print(f"[OUTPUT] {per_mb_path}")


if __name__ == "__main__":
    main()
