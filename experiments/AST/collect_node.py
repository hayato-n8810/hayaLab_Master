"""MBDiff.json から GumTree AST ノードの集合情報を抽出する。"""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import hayalab
from hayalab.classes.gumtree import GumDiff


def _extract_from_single_diff(mb_diff_data: dict) -> tuple[set[str], set[str], set[tuple[str, str]]]:
    """1件の差分データから name/value/name-value の集合を抽出する。"""
    diff_data = mb_diff_data.get("diff")
    if diff_data is None:
        return set(), set(), set()

    gumtree_diff = GumDiff.model_validate(diff_data)
    nodes = gumtree_diff.base_ast.tree + gumtree_diff.head_ast.tree

    local_name_set: set[str] = set()
    local_value_set: set[str] = set()
    local_name_value_set: set[tuple[str, str]] = set()

    for node in nodes:
        local_name_set.add(node.name)
        local_value_set.add(node.value)
        local_name_value_set.add((node.name, node.value))

    return local_name_set, local_value_set, local_name_value_set


def extract_node_sets(
    mb_diff_json: list[dict],
) -> tuple[set[str], set[str], set[tuple[str, str]]]:
    """差分データから name/value/name-value の集合を抽出する。

    Args:
            mb_diff_json (list[dict]): MBDiff.json の内容。

    Returns:
            tuple[set[str], set[str], set[tuple[str, str]]]:
                    (name 集合, value 集合, (name, value) 集合)
    """
    name_set: set[str] = set()
    value_set: set[str] = set()
    name_value_set: set[tuple[str, str]] = set()

    with ThreadPoolExecutor(max_workers=5) as executor:
        for local_name_set, local_value_set, local_name_value_set in executor.map(
            _extract_from_single_diff,
            mb_diff_json,
        ):
            name_set.update(local_name_set)
            value_set.update(local_value_set)
            name_value_set.update(local_name_value_set)

    return name_set, value_set, name_value_set


if __name__ == "__main__":
    from hayalab.config import PathConfig

    config = PathConfig()

    print("Loading MBDiff.json...")
    input_path = Path(config.processed) / "MBDiff.json"
    mb_diff_json = hayalab.read_json(str(input_path))

    print("Extracting node sets...")
    name_set, value_set, name_value_set = extract_node_sets(mb_diff_json)

    output_dir = Path(config.outputs) / "AST"

    # name ごとに value をまとめ、再現可能な順序で JSON 化する。
    name_to_values: dict[str, list[str]] = {}
    grouped_values: dict[str, set[str]] = defaultdict(set)
    for name, value in name_value_set:
        grouped_values[name].add(value)
    for name in sorted(grouped_values):
        name_to_values[name] = sorted(grouped_values[name])

    hayalab.write_json(
        str(output_dir / "gumtree_name_set.json"),
        sorted(name_set),
    )
    hayalab.write_json(
        str(output_dir / "gumtree_value_set.json"),
        sorted(value_set),
    )
    hayalab.write_json(
        str(output_dir / "gumtree_name_value_set.json"),
        name_to_values,
    )

    print(f"Input: {str(input_path)}")
    print(f"Output: {output_dir}")
    print(f"name_set size: {len(name_set)}")
    print(f"value_set size: {len(value_set)}")
    print(f"name_value_set size: {len(name_value_set)}")
