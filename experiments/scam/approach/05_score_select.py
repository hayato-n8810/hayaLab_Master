"""Stage 5: MB ごとのサイズスコア計算と最適 depth (L*) 選択を行う。

入力: `outputs/scam/approach/01_cutouts.json`  (Stage 1 出力)
出力: `outputs/scam/approach/05_selections.json`

スキーマ:
    [
        {
            "mb_id": int,
            "optimal_depth": int | null,         # 1..4 または null
            "optimal_abst_level": null,          # 呼び出し側で埋める前提
            "status": "selected" | "unrepresentable",
            "equivalence_class_id": null,
            "size_scores": {
                "1": { "rho": float, "sigma": float, "score": float, "weight_w": float },
                "2": { ... }, "3": { ... }, "4": { ... }
            }
        },
        ...
    ]

実行例:
    uv run python experiments/scam/approach/05_score_select.py --test
"""

from __future__ import annotations

import argparse
from pathlib import Path

import hayalab
from hayalab.classes.pattern import Cutout
from hayalab.config import PathConfig
from hayalab.pattern import compute_size_score, select_optimal_depth


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="Stage 5: size score + depth selection")
    parser.add_argument("--cutouts", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--weight-w", type=float, default=0.5)
    parser.add_argument(
        "--test",
        action="store_true",
        help="他ステージとの CLI 統一のためのフラグ（本ステージは MBDiff を直接読まない）",
    )
    return parser.parse_args()


def cutout_from_dict(d: dict) -> Cutout:
    """Dict → Cutout（diff_node_indices を set に戻す）。"""
    return Cutout.model_validate({**d, "diff_node_indices": set(d["diff_node_indices"])})


def main() -> None:
    """Stage 5 を実行する。"""
    args = parse_args()
    pc = PathConfig()
    output_dir = args.output_dir or (pc.outputs / "scam" / "approach")
    output_dir.mkdir(parents=True, exist_ok=True)
    cutouts_path = args.cutouts or (output_dir / "01_cutouts.json")
    output_path = output_dir / "05_selections.json"

    if not cutouts_path.exists():
        raise FileNotFoundError(f"Stage 1 出力が見つかりません: {cutouts_path}")
    print(f"[INPUT] {cutouts_path}", flush=True)

    cutouts_data = hayalab.read_json(str(cutouts_path))

    results: list[dict] = []
    for entry in cutouts_data:
        mb_id = entry["mb_id"]
        cutouts_by_depth: dict[int, list[Cutout]] = {}
        for depth_str, cuts in entry["cutouts"].items():
            cutouts_by_depth[int(depth_str)] = [cutout_from_dict(c) for c in cuts]

        # 各 depth でサイズスコアを計算（n_max は同 MB 内の最大）
        n_max = max(
            (sum(len(c.node_indices) for c in cuts) for cuts in cutouts_by_depth.values()),
            default=0,
        )
        size_scores: dict[str, dict] = {}
        for depth, cuts in sorted(cutouts_by_depth.items()):
            if not cuts:
                continue
            score = compute_size_score(cuts, n_max if n_max > 0 else 1, args.weight_w)
            size_scores[str(depth)] = score.model_dump(mode="json")

        selection = select_optimal_depth(mb_id, cutouts_by_depth, weight_w=args.weight_w)
        payload = selection.model_dump(mode="json")
        payload["size_scores"] = size_scores
        results.append(payload)

    hayalab.write_json(str(output_path), results)
    print(f"[OUTPUT] {output_path}", flush=True)
    n_sel = sum(1 for r in results if r["status"] == "selected")
    print(f"[SUMMARY] selected={n_sel} / total={len(results)}", flush=True)


if __name__ == "__main__":
    main()
