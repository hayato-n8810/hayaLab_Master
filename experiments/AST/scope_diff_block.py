"""MBDiff から差分ノード（差分ノード自身 + 配下）を抽出する。

出力は `scope_block_include_diff.py` と同様に、
- base_action ごとの抽出結果 (`per_action`)
- それらを統合し、元のASTインデックスで昇順ソートした結果 (`merged`)
を返す。

抽出ロジックは `hayalab.gumtree.extract.base_diff_blocks` を利用する。
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from os import cpu_count
from typing import Any

from tqdm import tqdm

import hayalab
from hayalab.classes.gumtree import ASTNode, GumDiff
from hayalab.config import PathConfig


def _diff_block_to_payloads(diff_block: dict[int, ASTNode]) -> list[dict[str, Any]]:
    """diff_blockの形式を整える

    Args:
        diff_block (dict[int, ASTNode]): ASTノードの辞書（元ASTインデックス，ASTNode）

    Returns:
        list[dict[str, Any]]: 整形されたノード情報のリスト
    """

    diff_block_payloads: list[dict[str, Any]] = []
    for index, node in sorted(diff_block.items(), key=lambda x: x[0]):
        diff_block_payloads.append(
            {
                "origin_index": index,
                "begin": node.begin,
                "end": node.end,
                "label": node.label,
                "name": node.name,
                "value": node.value,
                "parent": node.parent,
            }
        )

    return diff_block_payloads


def _process_record(item: dict[str, Any]) -> dict[str, Any]:
    """MBDiff 1実装対を scope_DIFF_BLOCK 形式に変換する

    Args:
        item (dict[str, Any]): 1実装対のASTと差分

    Returns:
        dict[str, Any]: 変換後の差分ブロック情報
    """
    record_id = item.get("id")
    diff_data = item.get("diff")

    # diff が無い実装対は空の形式でそのまま返す。
    if not diff_data:
        return {
            "id": record_id,
            "per_action": [],
            "merged": {"nodes": []},
        }

    gum_diff = GumDiff.model_validate(diff_data)

    # base_actions ごとに「差分ノード + 配下ノード」を収集する。
    per_action: list[dict[str, Any]] = []
    merged_nodes_map: dict[int, dict[str, Any]] = {}

    for block in hayalab.base_diff_blocks(gum_diff):
        nodes_payload = _diff_block_to_payloads(block.diff_block)
        per_action.append(
            {
                "action_index": block.action_index,
                "action_name": block.action_name,
                "action_tree": block.action_tree,
                "nodes": nodes_payload,
            }
        )

        for payload in nodes_payload:
            merged_nodes_map[payload["origin_index"]] = payload

    # 全 action を統合した差分ブロック（元AST index 昇順）
    merged_nodes = [merged_nodes_map[index] for index in sorted(merged_nodes_map)]

    return {
        "id": record_id,
        "per_action": per_action,
        "merged": {"nodes": merged_nodes},
    }


if __name__ == "__main__":
    config = PathConfig()

    input_path = config.data / "test_data" / "MBDiff_test.json"
    output_path = config.outputs / "AST" / "scope_DIFF_BLOCK.json"
    log_path = config.outputs / "AST" / "scope_DIFF_BLOCK.log"

    # 並列数。1にすると逐次実行。
    WORKERS = 6
    available_cpus = cpu_count() or 1
    workers = min(WORKERS, available_cpus)

    # 入力を読み込み、処理対象レンジを決定する。
    records = hayalab.read_json(str(input_path))
    total_records = len(records)

    # 実装対を変換する（必要なら並列実行）。
    if workers <= 1:
        result = [_process_record(item) for item in tqdm(records, total=len(records), desc="Processing")]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            result = list(tqdm(executor.map(_process_record, records), total=len(records), desc="Processing"))

    # 変換結果をJSONとして保存する。
    hayalab.write_json(str(output_path), result)

    log_lines = [
        f"入力={input_path}",
        f"出力={output_path}",
        f"全実装対数={total_records}",
        f"ワーカー数={workers}",
        f"処理実装対数={len(result)}",
    ]
    hayalab.write_file(str(log_path), "\n".join(log_lines) + "\n")

    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Log: {log_path}")
    print(f"Workers: {workers}")
    print(f"Processed 実装対数: {len(result)}")
