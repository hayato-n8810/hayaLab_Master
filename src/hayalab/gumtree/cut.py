"""base_actions を起点とした base_ast の切り出しと、切り出し結果の木構造化。

切り出しは包含関係をもつ 3 段のスコープを収集する。

1. diff — 差分ノードの begin / end に収まる要素。
2. parent_diff — diff に加えて、差分ノードと parent が完全一致する要素（兄弟）、
   parent[-1] を除いた parent のみをもち起点より index が小さい要素（親）、
   およびその最小 index 要素の begin と一致する要素。
3. around_parent — parent_diff に加えて、parent_diff の先頭要素を起点に、
   parent が完全一致する要素（兄弟）とその最小 index 要素の begin に一致する要素。

木構造化では、除去などで欠落した祖先を最近接の存在する祖先で置き換え、
仮想ルートで単一木に畳む。そこから集合類似度用のパス集合と、
木編集距離用の postorder 列を構成する。
"""

from __future__ import annotations

from typing import Any

from hayalab.classes.gumtree import ASTNode, GumDiff

from .extract import NodePayload, node_to_payload

# 切り出しスコープのキー（出力スキーマ安定化のため順序を固定する）。
SCOPE_KEYS: tuple[str, ...] = ("diff", "parent_diff", "around_parent")

# 仮想ルートのラベル。実ノードのラベルと衝突しない文字を用いる。
VIRTUAL_ROOT_LABEL: str = "⊤"


def cut_by_range(tree: list[ASTNode], start_index: int) -> list[NodePayload]:
    """起点ノードの文字範囲に収まる要素を収集する。

    Args:
        tree: base_ast のノード列。
        start_index: 起点ノードのインデックス。

    Returns:
        index 昇順のノード payload。
    """
    begin = tree[start_index].begin
    end = tree[start_index].end
    # parent が空の要素（program）は抽出対象から除く
    return [node_to_payload(index, node) for index, node in enumerate(tree) if node.parent and begin <= node.begin and node.end <= end]


def cut_by_parent(tree: list[ASTNode], start_index: int) -> dict[str, list[NodePayload]]:
    """起点ノードの parent 構造をもとに周辺要素を収集する。

    Args:
        tree: base_ast のノード列。
        start_index: 起点ノードのインデックス。

    Returns:
        収集結果（``parents_block``）と、再帰の起点になる インデックス（``parent_index``）。
    """
    parent = tree[start_index].parent
    parent_index = start_index

    # parent が完全一致する要素（兄弟要素）
    same_parent_nodes = [node_to_payload(index, node) for index, node in enumerate(tree) if node.parent and node.parent == parent]

    # 親要素
    # parent[-1] 以外の要素のみを parent にもち，起点より index が小さい要素
    outer_nodes: list[NodePayload] = []
    # parent[:-1]が空の場合，親要素はprogramのため無視
    if parent and len(parent[:-1]) > 0:
        upper_parent = parent[:-1]
        # 親は起点より index が小さい要素に限るため，先頭から start_index までを走査
        for index, node in enumerate(tree[:start_index]):
            if node.parent == upper_parent:
                outer_nodes.append(node_to_payload(index, node))
    # 構文としてのブロックを切り取る
    # 最小 index 要素の begin を基準に，そこから逆順に辿って begin が一致する要素
    begin_matched_nodes: list[NodePayload] = []
    if outer_nodes:
        parent_index = outer_nodes[0]["origin_index"]
        parent_begin = tree[parent_index].begin
        for index in range(parent_index, -1, -1):
            if tree[index].parent and tree[index].begin == parent_begin:
                begin_matched_nodes.append(node_to_payload(index, tree[index]))

    # 統合
    parents_block = same_parent_nodes + outer_nodes + begin_matched_nodes
    parents_block.sort(key=lambda x: x["origin_index"])

    return {"parent_index": parent_index, "parents_block": parents_block}


def merge_nodes(*groups: list[NodePayload]) -> list[NodePayload]:
    """複数のノード列を index 昇順・重複なしに統合する。

    Args:
        *groups: 統合するノード payload の列。

    Returns:
        base_ast.tree の index 昇順・重複なしのノード payload。
    """
    merged_map: dict[int, NodePayload] = {}
    for group in groups:
        for payload in group:
            merged_map[payload["origin_index"]] = payload
    return [merged_map[index] for index in sorted(merged_map)]


def cut_action_blocks(gum_diff: GumDiff) -> list[dict[str, Any]]:
    """base_actions ごとに 3 段スコープの切り出し結果を組み立てる。

    Args:
        gum_diff: 1 レコード分の差分解析結果。

    Returns:
        action ごとの切り出し結果（base_actions の順序を保持）。
    """
    tree = gum_diff.base_ast.tree
    blocks: list[dict[str, Any]] = []

    for action in gum_diff.base_actions:
        action_index = action.index
        if action_index is None or not (0 <= action_index < len(tree)):
            continue

        # 差分ノード集合
        diff_nodes = cut_by_range(tree, action_index)
        # 差分ノードの親ノード
        parent_result = cut_by_parent(tree, action_index)
        parent_diff_nodes = merge_nodes(diff_nodes, parent_result["parents_block"])

        # parent_diff の先頭要素を起点にさらに親と周辺を収集
        if parent_diff_nodes:
            around_result = cut_by_parent(tree, parent_result["parent_index"])
            around_parent_nodes = merge_nodes(parent_diff_nodes, around_result["parents_block"])

        blocks.append(
            {
                "action_index": action_index,
                "action_name": action.action,
                "diff": diff_nodes,
                "parent_diff": parent_diff_nodes,
                "around_parent": around_parent_nodes,
            }
        )

    return blocks


def merge_action_nodes(blocks: list[dict[str, Any]], key: str) -> list[NodePayload]:
    """Action ごとのノード列を 1 レコード分に統合する。

    Args:
        blocks: :func:`cut_action_blocks` の結果。
        key: 統合対象のキー（``diff`` / ``parent_diff`` / ``around_parent``）。

    Returns:
        base_ast.tree の index 昇順・重複なしのノード payload。
    """
    return merge_nodes(*(block[key] for block in blocks))


def _keyroots(leftmost: list[int]) -> list[int]:
    """Zhang-Shasha の keyroot 集合を postorder index の昇順で返す。

    Args:
        leftmost: 各 postorder 位置の最左葉 index。

    Returns:
        keyroot の postorder index（昇順）。
    """
    seen: set[int] = set()
    keyroots: list[int] = []
    for index in range(len(leftmost) - 1, -1, -1):
        if leftmost[index] not in seen:
            seen.add(leftmost[index])
            keyroots.append(index)
    keyroots.reverse()
    return keyroots
