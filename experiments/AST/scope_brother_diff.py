"""MBDiff から差分ノードと兄弟要素を抽出する。"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from os import cpu_count
from typing import Any

from tqdm import tqdm

import hayalab
from hayalab.classes.gumtree import ASTNode, GumDiff
from hayalab.config import PathConfig
from hayalab.gumtree.extract import get_descendants
from hayalab.gumtree.scan import find_scope_boundary_index

# スコープ境界とみなすノード名の集合
SCOPE_BOUNDARY: set[str] = {
    "program",  # トップレベルの全文（変数宣言・関数定義・式文など）
    # "statement_block",              # 粒度が大きい（他ノードを含有しすぎる）ので除外
    # ── ブロックレス可 制御構文 ─────────────────────────────
    "else_clause",  # else節の本体（statement_blockまたは単文）
    "if_statement",  # 条件部（parenthesized_expression）と then/else 本体
    "while_statement",  # 条件部（parenthesized_expression）とループ本体
    "do_statement",  # ループ本体と後置条件部（parenthesized_expression）
    "with_statement",  # with対象オブジェクトと本体
    "labeled_statement",  # ラベル付き文の本体
    "for_in_statement",  # ループ変数・イテラブル・本体（for-in / for-of）
    # ── switch ────────────────────────────────────────────
    "switch_case",  # case値（string/number）と各 case 節内の文群
    "switch_default",  # default 節内の文群
    "switch_body",  # switch全体のcase/default節リスト（{ }を含む）
    # ── for文（ヘッダー部と本体の両方を含む） ─────────────────
    "for_statement",  # 初期化・条件・更新（ヘッダー）とループ本体
    # ── 関数（アロー・式形式含む） ────────────────────────────
    "function",  # 関数宣言・関数式の引数リストと本体（statement_block）
    "arrow_function",  # 引数リスト・=>・本体（statement_blockまたは式）
    "function_declaration",  # 関数名・引数リスト・本体（statement_block）
    "function_expression",  # 無名/名前付き関数式の引数リスト・本体
    "generator_function_declaration",  # ジェネレータ関数名・*・引数リスト・本体
    "generator_function",  # ジェネレータ関数式の引数リスト・本体
    # ── 例外処理 ──────────────────────────────────────────
    "try_statement",  # try本体・catch節・finally節の全体
    "finally_clause",  # finally節の本体（statement_block）
    # ── クラス ────────────────────────────────────────────
    "class_body",  # クラス内のメソッド定義・フィールド定義の列
    "method_definition",  # メソッド名・引数リスト・本体（statement_block）
    "class_static_block",  # static { } ブロック内の文群
}


def _to_node_payload(index: int, node: ASTNode) -> dict[str, int | str | list[int]]:
    """元のAST形式を維持したノード情報に整形する。

    Args:
            index: base_ast 内のノードインデックス。
            node: ASTノード。

    Returns:
            dict[str, int | str | list[int]]: 変換済みノード情報。
    """
    return {
        "origin_index": index,
        "begin": node.begin,
        "end": node.end,
        "label": node.label,
        "name": node.name,
        "value": node.value,
        "parent": node.parent,
    }


def _get_sibling_root_indices(
    tree: list[ASTNode],
    action_index: int,
    scope_idx: int | None,
) -> list[int]:
    """差分ノードの兄弟要素（同一親を持つ直下ノード）のインデックスを取得する。

    Args:
            tree: base_ast のノード列。
            action_index: 差分ノードのインデックス。
            scope_idx: スコープ境界ノードのインデックス。

    Returns:
            list[int]: 兄弟要素のインデックス（差分ノードを含む）。
    """
    if scope_idx is None:
        return []
    if action_index == scope_idx:
        return []

    action_node = tree[action_index]
    action_node_parent = action_node.parent
    if not action_node_parent:
        return []

    # 差分ノードにおける，スコープ境界ノードの一つ下の階層を兄弟判定に利用する
    scope = action_node_parent.index(scope_idx)
    if scope + 1 >= len(action_node_parent):
        return []
    parent_idx = action_node_parent[scope + 1]
    if parent_idx is None or not (0 <= parent_idx < len(tree)):
        return []

    sibling_indices: list[int] = []
    for idx, node in enumerate(tree):
        if not node.parent:
            continue
        if node.parent[-1] != parent_idx:
            continue
        if scope_idx not in node.parent:
            continue
        sibling_indices.append(idx)

    return sorted(sibling_indices)


def _collect_sibling_nodes(
    tree: list[ASTNode],
    action_index: int,
    scope_idx: int | None,
) -> list[dict[str, int | str | list[int]]]:
    """差分ノードと兄弟要素の部分木を収集してpayload化する。

    Args:
            tree: base_ast のノード列。
            action_index: 差分ノードのインデックス。
            scope_idx: スコープ境界ノードのインデックス。

    Returns:
            list[dict[str, int | str | list[int]]]: 収集したノードpayload。
    """
    sibling_roots = _get_sibling_root_indices(tree, action_index, scope_idx)
    nodes_map: dict[int, dict[str, int | str | list[int]]] = {}

    # 兄弟要素の部分木を収集する。
    for root_idx in sibling_roots:
        for index, node in get_descendants(root_idx, tree):
            if scope_idx is not None and index == scope_idx:
                continue
            nodes_map[index] = _to_node_payload(index, node)

    # 差分ノード自身の部分木も収集する。
    for index, node in get_descendants(action_index, tree):
        if scope_idx is not None and index == scope_idx:
            continue
        nodes_map[index] = _to_node_payload(index, node)

    return [nodes_map[index] for index in sorted(nodes_map)]


def _process_record(item: dict[str, Any]) -> dict[str, Any]:
    """MBDiff 1実装対を scope_BROTHER_DIFF 形式に変換する。

    Args:
            item: 1実装対のレコード。

    Returns:
            dict[str, Any]: 変換結果。
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
    tree = gum_diff.base_ast.tree
    per_action: list[dict[str, Any]] = []
    merged_nodes_map: dict[int, dict[str, int | str | list[int]]] = {}

    # base_actions ごとにスコープ境界内の兄弟要素を収集する。
    for action in gum_diff.base_actions:
        action_index = action.index
        scope_idx: int | None = None
        scope_name: str | None = None
        nodes: list[dict[str, int | str | list[int]]] = []

        if action_index is not None and 0 <= action_index < len(tree):
            scope_idx = find_scope_boundary_index(tree[action_index], tree, SCOPE_BOUNDARY)
            if scope_idx is not None:
                scope_name = tree[scope_idx].name
                nodes = _collect_sibling_nodes(tree, action_index, scope_idx)
                for node_payload in nodes:
                    merged_nodes_map[node_payload["origin_index"]] = node_payload

        per_action.append(
            {
                "action_index": action_index,
                "action_name": action.action,
                "action_tree": action.tree,
                "scope_index": scope_idx,
                "scope_name": scope_name,
                "nodes": nodes,
            }
        )

    # per_action の全ノードを index 昇順で統合する。
    merged_nodes = [merged_nodes_map[index] for index in sorted(merged_nodes_map)]
    return {
        "id": record_id,
        "per_action": per_action,
        "merged": {"nodes": merged_nodes},
    }


def result_statics(target_records: list[dict[str, Any]], result: list[dict[str, Any]]) -> dict[str, Any]:
    """抽出結果の一致性に関する統計情報を集計する。

    Args:
            target_records: 入力実装対（処理対象範囲）。
            result: 変換結果。

    Returns:
            dict[str, Any]: 統計情報。
    """
    full_match_with_original_count = 0
    full_match_with_original_ids: list[int] = []

    per_action_merged_exact_action_count = 0
    per_action_merged_exact_action_ids: list[str] = []

    per_action_merged_exact_record_count = 0
    per_action_merged_exact_record_ids: list[int] = []

    per_action_all_equal_record_count = 0
    per_action_all_equal_record_ids: list[int] = []

    per_action_equal_pairs_count = 0
    per_action_equal_pairs_ids: list[str] = []

    per_action_total_count = 0

    for origin_item, result_item in zip(target_records, result):
        record_id = result_item.get("id", origin_item.get("id"))
        diff_data = origin_item.get("diff")
        per_actions = result_item.get("per_action", [])
        merged_nodes = result_item.get("merged", {}).get("nodes", [])

        # merged の収集結果が base_ast の全ノード（payload化後）と一致するかを判定する。
        if diff_data:
            gum_diff = GumDiff.model_validate(diff_data)
            origin_all_nodes = [_to_node_payload(index, node) for index, node in enumerate(gum_diff.base_ast.tree)]
            if merged_nodes == origin_all_nodes:
                full_match_with_original_count += 1
                if record_id is not None:
                    full_match_with_original_ids.append(record_id)

        # per_action と merged の完全一致を action 単位/record 単位で集計する。
        action_nodes_list = [action.get("nodes", []) for action in per_actions]
        per_action_total_count += len(action_nodes_list)
        exact_action_count = sum(1 for action_nodes in action_nodes_list if action_nodes == merged_nodes)
        per_action_merged_exact_action_count += exact_action_count
        for action in per_actions:
            if action.get("nodes", []) == merged_nodes:
                per_action_merged_exact_action_ids.append(f"{record_id}:{action.get('action_index')}")
        if action_nodes_list and exact_action_count == len(action_nodes_list):
            per_action_merged_exact_record_count += 1
            if record_id is not None:
                per_action_merged_exact_record_ids.append(record_id)

        # per_action 同士の完全一致を pair 単位と record 単位で集計する。
        if len(action_nodes_list) >= 2:
            all_equal = True
            equal_pair_count = 0
            for i in range(len(action_nodes_list)):
                for j in range(i + 1, len(action_nodes_list)):
                    if action_nodes_list[i] == action_nodes_list[j]:
                        equal_pair_count += 1
                        left_action_index = per_actions[i].get("action_index")
                        right_action_index = per_actions[j].get("action_index")
                        per_action_equal_pairs_ids.append(f"{record_id}:{left_action_index}-{right_action_index}")
                    else:
                        all_equal = False
            per_action_equal_pairs_count += equal_pair_count
            if all_equal:
                per_action_all_equal_record_count += 1
                if record_id is not None:
                    per_action_all_equal_record_ids.append(record_id)

    return {
        "full_match_with_original_count": full_match_with_original_count,
        "full_match_with_original_ids": full_match_with_original_ids,
        "per_action_merged_exact_action_count": per_action_merged_exact_action_count,
        "per_action_merged_exact_action_ids": per_action_merged_exact_action_ids,
        "per_action_merged_exact_record_count": per_action_merged_exact_record_count,
        "per_action_merged_exact_record_ids": per_action_merged_exact_record_ids,
        "per_action_all_equal_record_count": per_action_all_equal_record_count,
        "per_action_all_equal_record_ids": per_action_all_equal_record_ids,
        "per_action_equal_pairs_count": per_action_equal_pairs_count,
        "per_action_equal_pairs_ids": per_action_equal_pairs_ids,
        "per_action_total_count": per_action_total_count,
    }


if __name__ == "__main__":
    config = PathConfig()

    # 実行設定をここで一括指定する（CLIは使わない）。
    input_path = config.data / "processed" / "MBDiff.json"
    output_path = config.outputs / "AST" / "scope_BROTHER_DIFF_target.json"
    log_path = config.outputs / "AST" / "scope_BROTHER_DIFF_target.log"
    WORKERS = 6

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    workers = WORKERS if cpu_count() < WORKERS else cpu_count()
    start = 0
    end: int | None = None

    # 入力を読み込み、処理対象レンジを決定する。
    records = hayalab.read_json(str(input_path))
    target_ids = {222, 609, 791, 902, 1206, 1306, 1691, 2512, 2919, 6182, 8126, 14412, 21294, 23864}
    records = [r for r in records if r.get("id") in target_ids]
    total_records = len(records)

    # 実装対を変換する（必要なら並列実行）。
    if workers <= 1:
        result = [_process_record(item) for item in tqdm(records, total=len(records), desc="Processing")]
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            result = list(tqdm(executor.map(_process_record, records), total=len(records), desc="Processing"))

    # 変換結果をJSONとして保存する。
    hayalab.write_json(str(output_path), result)

    # # 変換結果の一致性に関する統計情報を集計する。
    # stats = result_statics(records, result)

    # # 実行統計をログファイルへ保存する。
    # log_lines = [
    #     f"入力={input_path}",
    #     f"出力={output_path}",
    #     f"全実装対数={total_records}",
    #     f"ワーカー数={workers}",
    #     f"処理実装対数={len(result)}",
    #     f"merged.nodes が base_ast の全ノードと完全一致={stats['full_match_with_original_count']}",
    #     f"merged.nodes が base_ast の全ノードと完全一致したID={','.join(map(str, stats['full_match_with_original_ids']))}",
    #     # ある1つの per_action エントリの nodes が merged.nodes と完全一致したアクション単位の数とID（実装対ID:action_index 形式）
    #     f"per_actionとmergedが完全一致した件数（編集操作ごと）={stats['per_action_merged_exact_action_count']}",
    #     f"per_actionとmergedが完全一致したID（実装対ID:action_index）={','.join(stats['per_action_merged_exact_action_ids'])}",
    #     # 全アクションの nodes が merged.nodes と一致した実装対の数とID。つまりアクションが1つ、またはすべて同じスコープに収まっている
    #     f"per_actionとmergedが完全一致した件数（実装対ごと）={stats['per_action_merged_exact_record_count']}",
    #     f"per_actionとmergedが完全一致した実装対ID）={','.join(map(str, stats['per_action_merged_exact_record_ids']))}",
    #     # 同一実装対内の複数アクション間で nodes がすべて互いに一致した実装対の数とID。複数の差分が同じスコープ
    #     f"per_action同士がすべて完全一致した件数={stats['per_action_all_equal_record_count']}",
    #     f"per_action同士がすべて完全一致した実装対ID={','.join(map(str, stats['per_action_all_equal_record_ids']))}",
    #     # 同一実装対内のアクションを2つずつ比較したとき、nodes が一致したペアの数とID（実装対ID:actionA-actionB 形式）
    #     f"per_action同士が完全一致したpair件数={stats['per_action_equal_pairs_count']}",
    #     f"per_action同士が完全一致したpairID(実装対ID:actionA-actionB)={','.join(stats['per_action_equal_pairs_ids'])}",
    #     # 処理した編集操作の総数
    #     f"処理した編集操作の総数={stats['per_action_total_count']}",
    # ]
    # hayalab.write_file(str(log_path), "\n".join(log_lines) + "\n")

    print(f"Input: {input_path}")
    print(f"Output: {output_path}")
    print(f"Log: {log_path}")
    print(f"Workers: {workers}")
    print(f"Processed 実装対数: {len(result)}")
