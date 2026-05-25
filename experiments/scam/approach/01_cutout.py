"""Stage 1: 全 MB について 4 粒度の AST 切り出しを行い、統合 JSON に保存する。

入力: MBDiff JSON (`{"id": int, "diff": GumDiff JSON, ...}` のリスト)
出力: `outputs/scam/approach/01_cutouts.json`

切り出しロジックは `hayalab.gumtree.extract.cut_scope_*` を採用し、
SCOPE_BOUNDARY は `hayalab.config.pattern_config.SCOPE_BOUNDARY` で統一する。

スキーマ:
    [
        {
            "id": int,                           # MBDiff の id
            "cutouts": {
                "Diff":     {"diff_node_indices": [int,...], "nodes": [...]},
                "Brother":  {"diff_node_indices": [int,...], "nodes": [...]},
                "ExParent": {"diff_node_indices": [int,...], "nodes": [...]},
                "Parent":   {"diff_node_indices": [int,...], "nodes": [...]}
            }
        },
        ...
    ]

ノード payload: {"origin_index", "begin", "end", "label", "name", "value", "parent"}
`diff_node_indices` は各 scope の `nodes` の `origin_index` のうち `Diff` の merged に含まれるもの。
Diff 自身では `Diff.nodes` 全体の `origin_index` 集合に等しい。

実行例:
    uv run python experiments/scam/approach/01_cutout.py --test
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import hayalab
from hayalab.classes.gumtree import GumDiff
from hayalab.config import PathConfig
from hayalab.config.pattern_config import SCOPE_BOUNDARY
from hayalab.gumtree.extract import (
    base_scope_block_exclude_parent,
    base_scope_block_include_parent,
    base_scope_brother,
    base_scope_diff,
)


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="Stage 1: AST cutout (4 granularities)")
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


def _build_cutout_entry(nodes: list[dict[str, Any]], diff_origin_set: set[int]) -> dict[str, Any]:
    """1 scope の merged.nodes から新スキーマ {diff_node_indices, nodes} を作る。

    diff_node_indices は `nodes` の origin_index のうち diff_origin_set に含まれるものを昇順で。
    """
    in_scope_diff = sorted({n["origin_index"] for n in nodes} & diff_origin_set)
    return {"diff_node_indices": in_scope_diff, "nodes": nodes}


def build_cutouts_for_mb(gum_diff: GumDiff) -> dict[str, dict[str, Any]]:
    """1 MB の 4 粒度 cutout (Diff/Brother/ExParent/Parent) を構築する。"""
    diff_result = base_scope_diff(gum_diff)
    brother_result = base_scope_brother(gum_diff)
    ex_parent_result = base_scope_block_exclude_parent(gum_diff, SCOPE_BOUNDARY)
    parent_result = base_scope_block_include_parent(gum_diff, SCOPE_BOUNDARY)

    diff_nodes = diff_result["merged"]["nodes"]
    diff_origin_set: set[int] = {n["origin_index"] for n in diff_nodes}

    return {
        "Diff": _build_cutout_entry(diff_nodes, diff_origin_set),
        "Brother": _build_cutout_entry(brother_result["merged"]["nodes"], diff_origin_set),
        "ExParent": _build_cutout_entry(ex_parent_result["merged"]["nodes"], diff_origin_set),
        "Parent": _build_cutout_entry(parent_result["merged"]["nodes"], diff_origin_set),
    }


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

    results: list[dict[str, Any]] = []
    for rec in records:
        record_id = rec["id"]
        gum_diff = GumDiff.model_validate(rec["diff"])
        cutouts = build_cutouts_for_mb(gum_diff)
        results.append({"id": record_id, "cutouts": cutouts})

    hayalab.write_json(str(output_path), results)
    print(f"[OUTPUT] {output_path}", flush=True)
    total = sum(len(r["cutouts"]) for r in results)
    print(f"[SUMMARY] {len(results)} MBs × 4 cutouts = {total}", flush=True)


if __name__ == "__main__":
    main()
