"""RQ1: サイズスコア重み w の感度分析。

`outputs/scam/approach/01_cutouts.json` を読み込み、w ∈ {0.0, 0.25, 0.5, 0.75, 1.0} で
各 MB の L* を計算し、L1..L4 選択比率・平均 ρ(L*)・平均 |N(L*)| を集計する。

入力: `outputs/scam/approach/01_cutouts.json` (Stage 1 出力)
出力: `outputs/scam/rq1/rq1_sensitivity.csv`

実行例:
    uv run python experiments/scam/rq1_size_score_sensitivity.py
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import hayalab
from hayalab.classes.pattern import Cutout
from hayalab.config import PathConfig
from hayalab.pattern import compute_size_score, select_optimal_depth


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="RQ1 size score sensitivity")
    parser.add_argument("--cutouts", type=Path, default=None, help="Stage 1 出力パス")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--weights",
        type=float,
        nargs="+",
        default=[0.0, 0.25, 0.5, 0.75, 1.0],
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="他スクリプトとの CLI 統一用フラグ（cutouts 既定パスは共通）",
    )
    return parser.parse_args()


def cutout_from_dict(d: dict) -> Cutout:
    """Dict → Cutout (set 復元)。"""
    return Cutout.model_validate({**d, "diff_node_indices": set(d["diff_node_indices"])})


def main() -> None:
    """RQ1 を実行する。"""
    args = parse_args()
    pc = PathConfig()
    cutouts_path = args.cutouts or (pc.outputs / "scam" / "approach" / "01_cutouts.json")
    output_dir = args.output_dir or (pc.outputs / "scam" / "rq1")
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "rq1_sensitivity.csv"

    if not cutouts_path.exists():
        raise FileNotFoundError(f"Stage 1 出力が見つかりません: {cutouts_path} (先に approach/01_cutout.py を実行してください)")
    print(f"[INPUT] {cutouts_path}", flush=True)

    cutouts_data = hayalab.read_json(str(cutouts_path))
    print(f"[RECORDS] {len(cutouts_data)}", flush=True)

    # 全 MB の depth 別 cutouts を Pydantic 復元
    cutouts_by_mb: dict[int, dict[int, list[Cutout]]] = {}
    for entry in cutouts_data:
        mb_id = entry["mb_id"]
        cutouts_by_mb[mb_id] = {int(depth_str): [cutout_from_dict(c) for c in cuts] for depth_str, cuts in entry["cutouts"].items()}

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "w",
                "L1_ratio",
                "L2_ratio",
                "L3_ratio",
                "L4_ratio",
                "unrepresentable_ratio",
                "mean_rho",
                "mean_size",
            ]
        )
        for w in args.weights:
            print(f"  w={w:.2f}", flush=True)
            depth_counts = {1: 0, 2: 0, 3: 0, 4: 0}
            unrepresentable = 0
            rhos: list[float] = []
            sizes: list[int] = []

            for mb_id, cutouts_by_depth in cutouts_by_mb.items():
                sel = select_optimal_depth(mb_id, cutouts_by_depth, weight_w=w)
                if sel.status != "selected" or sel.optimal_depth is None:
                    unrepresentable += 1
                    continue
                d = sel.optimal_depth
                depth_counts[d] += 1
                cuts = cutouts_by_depth[d]
                n_max = max(sum(len(c.node_indices) for c in cb) for cb in cutouts_by_depth.values()) or 1
                score = compute_size_score(cuts, n_max, w)
                rhos.append(score.rho)
                sizes.append(sum(len(c.node_indices) for c in cuts))

            total = sum(depth_counts.values()) + unrepresentable
            denom = max(total, 1)
            writer.writerow(
                [
                    f"{w:.2f}",
                    f"{depth_counts[1] / denom:.4f}",
                    f"{depth_counts[2] / denom:.4f}",
                    f"{depth_counts[3] / denom:.4f}",
                    f"{depth_counts[4] / denom:.4f}",
                    f"{unrepresentable / denom:.4f}",
                    f"{(sum(rhos) / len(rhos)) if rhos else 0.0:.4f}",
                    f"{(sum(sizes) / len(sizes)) if sizes else 0.0:.4f}",
                ]
            )

    print(f"[OUTPUT] {csv_path}", flush=True)


if __name__ == "__main__":
    main()
