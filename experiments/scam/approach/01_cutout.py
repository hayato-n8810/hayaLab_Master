"""Stage 1: 全 MB について 4 種の depth で AST 切り出しを行い、結果を保存する。

入力: MBDiff JSON (`{"id": int, "diff": GumDiff JSON, ...}` のリスト)
出力: `outputs/scam/approach/01_cutouts.json`

スキーマ:
    [
        {
            "mb_id": int,                       # MBDiff の id（一貫識別子）
            "cutouts": {
                "1": [ { "mb_id": int, "depth": 1, "root_index": int,
                         "node_indices": [int, ...], "diff_node_indices": [int, ...] }, ... ],
                "2": [...], "3": [...], "4": [...]
            }
        },
        ...
    ]

実行例:
    uv run python experiments/scam/approach/01_cutout.py --test
"""

from __future__ import annotations

import argparse
from pathlib import Path

import hayalab
from hayalab.classes.gumtree import GumDiff
from hayalab.config import PathConfig
from hayalab.pattern import cut_diff_all_depths


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="Stage 1: AST cutout")
    parser.add_argument("--input", type=Path, default=None, help="MBDiff JSON path")
    parser.add_argument("--test", action="store_true", help="use data/test_data/MBDiff_target.json")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def determine_input(args: argparse.Namespace, pc: PathConfig) -> Path:
    """入力パス決定。"""
    if args.input is not None:
        return args.input
    if args.test:
        return pc.data / "test_data" / "MBDiff_target.json"
    return pc.processed / "MBDiff.json"


def cutout_to_dict(c) -> dict:
    """Cutout を JSON シリアライズ可能な dict に変換する（set フィールドをソート列に）。"""
    payload = c.model_dump(mode="json")
    payload["diff_node_indices"] = sorted(c.diff_node_indices)
    return payload


def main() -> None:
    """Stage 1 を実行する。"""
    args = parse_args()
    pc = PathConfig()
    input_path = determine_input(args, pc)
    output_dir = args.output_dir or (pc.outputs / "scam" / "approach")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "01_cutouts.json"

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")
    print(f"[INPUT] {input_path}", flush=True)
    records = sorted(hayalab.read_json(str(input_path)), key=lambda r: r["id"])
    print(f"[RECORDS] {len(records)}", flush=True)

    results: list[dict] = []
    for rec in records:
        mb_id = rec["id"]
        diff = GumDiff.model_validate(rec["diff"])
        cutouts_by_depth = cut_diff_all_depths(diff, mb_id)
        results.append(
            {
                "mb_id": mb_id,
                "cutouts": {str(depth): [cutout_to_dict(c) for c in cutouts_by_depth[depth]] for depth in sorted(cutouts_by_depth.keys())},
            }
        )

    hayalab.write_json(str(output_path), results)
    print(f"[OUTPUT] {output_path}", flush=True)


if __name__ == "__main__":
    main()
