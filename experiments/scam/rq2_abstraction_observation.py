"""RQ2: 抽象化レベル選択（集約観測量ベース）。

`outputs/scam/approach/04_equivalence_classes.json` を読み込み、N_classes / N_aggregated /
N_just_match / MB_in_aggregated / MaxClassSize / Migration(A→A+1) を算出する。

入力: `outputs/scam/approach/04_equivalence_classes.json` (Stage 4 出力)
出力:
    - `outputs/scam/rq2/rq2_observation.csv`
    - `outputs/scam/rq2/rq2_observation.json`

実行例:
    uv run python experiments/scam/rq2_abstraction_observation.py
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import hayalab
from hayalab.classes.pattern import EquivalenceClass
from hayalab.config import PathConfig
from hayalab.pattern import compute_abstraction_observations


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="RQ2 abstraction observation")
    parser.add_argument("--classes", type=Path, default=None, help="Stage 4 出力パス")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--test", action="store_true", help="CLI 統一用フラグ")
    return parser.parse_args()


def class_from_dict(d: dict) -> EquivalenceClass:
    """Dict → EquivalenceClass (検出結果 を set 復元)。"""
    return EquivalenceClass.model_validate({**d, "detect_id": set(d["detect_id"])})


def main() -> None:
    """RQ2 を実行する。"""
    args = parse_args()
    pc = PathConfig()
    classes_path = args.classes or (pc.outputs / "scam" / "approach" / "04_equivalence_classes.json")
    output_dir = args.output_dir or (pc.outputs / "scam" / "rq2")
    output_dir.mkdir(parents=True, exist_ok=True)

    if not classes_path.exists():
        raise FileNotFoundError(f"Stage 4 出力が見つかりません: {classes_path} (先に approach/04_aggregate.py を実行してください)")
    print(f"[INPUT] {classes_path}", flush=True)

    raw = hayalab.read_json(str(classes_path))
    classes_by_level: dict[int, list[EquivalenceClass]] = {}
    for level_str, clist in raw.items():
        classes_by_level[int(level_str)] = [class_from_dict(c) for c in clist]

    # mb_id × abst_level → class_id の所属マップ
    mb_class_assignment: dict[int, dict[int, str]] = {}
    for level, classes in classes_by_level.items():
        for cls in classes:
            for mb_id in cls.detect_id:
                mb_class_assignment.setdefault(mb_id, {})[level] = cls.class_id

    observations = compute_abstraction_observations(classes_by_level, mb_class_assignment)

    csv_path = output_dir / "rq2_observation.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "abst_level",
                "n_classes",
                "n_aggregated",
                "n_just_match",
                "mb_in_aggregated",
                "max_class_size",
                "migration_to_next",
            ]
        )
        for o in observations:
            writer.writerow(
                [
                    o.abst_level,
                    o.n_classes,
                    o.n_aggregated,
                    o.n_just_match,
                    o.mb_in_aggregated,
                    o.max_class_size,
                    "" if o.migration_to_next is None else o.migration_to_next,
                ]
            )

    json_path = output_dir / "rq2_observation.json"
    hayalab.write_json(str(json_path), [o.model_dump(mode="json") for o in observations])

    print(f"[OUTPUT] {csv_path}", flush=True)
    for o in observations:
        print(
            f"  A{o.abst_level}: classes={o.n_classes}, aggregated={o.n_aggregated}, "
            f"just_match={o.n_just_match}, mb_in_agg={o.mb_in_aggregated}, "
            f"max={o.max_class_size}, migration→next={o.migration_to_next}",
            flush=True,
        )


if __name__ == "__main__":
    main()
