"""Stage 2: 各 mb_id × depth × abst_level の組合せで Pattern を生成し、結果を保存する。

入力:
    - `outputs/scam/approach/01_cutouts.json`  (Stage 1 出力)
    - MBDiff JSON (`base_ast` を Pattern 生成時に参照)

出力: `outputs/scam/approach/02_patterns.json`

スキーマ:
    [
        {
            "mb_id": int,
            "patterns": {
                "0": [ { "mb_id": int, "depth": int, "abst_level": 0,
                         "ast_template": [...], "regex_template": "...",
                         "signature": "..." }, ... ],
                "1": [...], "2": [...], "3": [...]
            }
        },
        ...
    ]

実行例:
    uv run python experiments/scam/approach/02_abstract.py --test
"""

from __future__ import annotations

import argparse
from pathlib import Path

import hayalab
from hayalab.classes.gumtree import GumDiff
from hayalab.classes.pattern import Cutout
from hayalab.config import PathConfig
from hayalab.pattern import abstract_cutout


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="Stage 2: pattern abstraction")
    parser.add_argument("--input", type=Path, default=None, help="MBDiff JSON path")
    parser.add_argument("--test", action="store_true", help="use data/test_data/MBDiff_target.json")
    parser.add_argument(
        "--cutouts",
        type=Path,
        default=None,
        help="Stage 1 出力 (outputs/scam/approach/01_cutouts.json) のパス",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def determine_input(args: argparse.Namespace, pc: PathConfig) -> Path:
    """入力 MBDiff JSON のパス決定。"""
    if args.input is not None:
        return args.input
    if args.test:
        return pc.data / "test_data" / "MBDiff_target.json"
    return pc.processed / "MBDiff.json"


def main() -> None:
    """Stage 2 を実行する。"""
    args = parse_args()
    pc = PathConfig()
    input_path = determine_input(args, pc)
    output_dir = args.output_dir or (pc.outputs / "scam" / "approach")
    output_dir.mkdir(parents=True, exist_ok=True)
    cutouts_path = args.cutouts or (output_dir / "01_cutouts.json")
    output_path = output_dir / "02_patterns.json"

    if not cutouts_path.exists():
        raise FileNotFoundError(f"Stage 1 出力が見つかりません: {cutouts_path}")
    if not input_path.exists():
        raise FileNotFoundError(f"MBDiff JSON が見つかりません: {input_path}")

    print(f"[INPUT] cutouts={cutouts_path}", flush=True)
    print(f"[INPUT] mbdiff={input_path}", flush=True)

    cutouts_data = hayalab.read_json(str(cutouts_path))
    mbdiff_records = {r["id"]: r for r in hayalab.read_json(str(input_path))}

    results: list[dict] = []
    for entry in cutouts_data:
        mb_id = entry["mb_id"]
        if mb_id not in mbdiff_records:
            raise KeyError(f"mb_id {mb_id} が MBDiff に存在しません")
        diff = GumDiff.model_validate(mbdiff_records[mb_id]["diff"])
        ast = diff.base_ast

        patterns_by_level: dict[str, list[dict]] = {"0": [], "1": [], "2": [], "3": []}
        # entry["cutouts"] は { "1": Cutout, "2": Cutout, ... } の dict（1 depth = 1 Cutout）
        for cut_dict in entry["cutouts"].values():
            cutout = Cutout.model_validate(
                {
                    **cut_dict,
                    "diff_node_indices": set(cut_dict["diff_node_indices"]),
                }
            )
            if not cutout.node_indices:
                # 差分アクションが空 / index が無効な MB は depth ごと Cutout が空になる。
                # Stage 1 仕様（cutout.py: 空 Cutout を返す）に合わせて、ここではスキップする。
                continue
            for abst_level in (0, 1, 2, 3):
                pattern = abstract_cutout(cutout, ast, abst_level)
                patterns_by_level[str(abst_level)].append(pattern.model_dump(mode="json"))

        results.append({"mb_id": mb_id, "patterns": patterns_by_level})

    hayalab.write_json(str(output_path), results)
    print(f"[OUTPUT] {output_path}", flush=True)


if __name__ == "__main__":
    main()
