"""GumTree ASTからノードを収集する処理を提供するモジュール。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from hayalab.classes.gumtree import AST, ActionBlock, ASTNode, GumAction, GumDiff
from hayalab.gumtree.scan import find_scope_boundary_index, find_sibling_root_indices

NodePayload = dict[str, int | str | list[int]]


# ──────────────────────────────────────────────────────────
# 差分ブロック収集（既存 API）
# ──────────────────────────────────────────────────────────


def cut_diff_blocks(
    ast: AST,
    actions: list[GumAction],
    target_actions: list[str] | None = None,
) -> Iterator[ActionBlock]:
    """差分アクションから対象ノード群を収集する。

    Args:
        ast (AST): 対象AST。
        actions (list[GumAction]): 差分アクション。
        target_actions (list[str] | None): 対象アクション名。

    Returns:
        Iterator[ActionBlock]: アクションごとの差分ブロック。
    """
    origin_ast_tree = ast.tree

    for action in actions:
        diff_block: dict[int, ASTNode] = {}
        if action.index is None or action.index < 0 or action.index >= len(origin_ast_tree):
            continue

        # 対象差分ASTノード
        action_node = origin_ast_tree[action.index]
        action_name = action.action
        # 差分ノードの親ノードインデックス集合（これをparentに含むノードは差分配下にある）
        action_parent = set(action_node.parent)
        action_parent.add(action.index)

        if target_actions is not None and action_name not in target_actions:
            continue

        # 差分ノードとその配下ノードを収集（元のASTにおける位置（index）は保持）
        diff_block[action.index] = action_node
        base_idx = action.index
        for node in origin_ast_tree[action.index :]:
            if set(node.parent) >= action_parent:
                base_idx += 1
                diff_block[base_idx] = node

        # 変更操作と元のASTにおける情報を付加して差分ブロックを返す
        yield ActionBlock(
            action_index=action.index,
            action_name=action_name,
            action_tree=action.tree,
            diff_block={idx: diff_block[idx] for idx in sorted(diff_block)},
        )


def base_diff_blocks(gumtree_diff: GumDiff, target_actions: list[str] | None = None) -> Iterator[ActionBlock]:
    """変更前(base)側ASTから差分ノード群を収集する。"""
    return cut_diff_blocks(gumtree_diff.base_ast, gumtree_diff.base_actions, target_actions)


def head_diff_blocks(gumtree_diff: GumDiff, target_actions: list[str] | None = None) -> Iterator[ActionBlock]:
    """変更後(head)側ASTから差分ノード群を収集する。"""
    return cut_diff_blocks(gumtree_diff.head_ast, gumtree_diff.head_actions, target_actions)


def get_descendants(scope_idx: int, tree: list[ASTNode]) -> list[tuple[int, ASTNode]]:
    """指定スコープ配下の子孫ノードを収集する。

    Args:
        scope_idx (int): スコープ境界ノード index。
        tree (list[ASTNode]): ASTノード列。

    Returns:
        list[tuple[int, ASTNode]]: index 昇順の子孫ノード情報。
    """
    descendants: list[tuple[int, ASTNode]] = []
    # スコープ境界ノードを含める
    descendants.append((scope_idx, tree[scope_idx]))
    for index, node in enumerate(tree):
        if scope_idx in node.parent:
            descendants.append((index, node))
    return descendants


# ──────────────────────────────────────────────────────────
# ノード payload 変換
# ──────────────────────────────────────────────────────────


def node_to_payload(index: int, node: ASTNode) -> NodePayload:
    """ASTノードをJSON出力形式の辞書に変換する。

    Args:
        index: base_ast 内のノードインデックス。
        node: ASTノード。

    Returns:
        NodePayload: 変換済みノード情報。
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


# ──────────────────────────────────────────────────────────
# スコープ収集（内部ヘルパー）
# ──────────────────────────────────────────────────────────


def _collect_sibling_nodes(
    tree: list[ASTNode],
    action_index: int,
    scope_idx: int,
) -> list[NodePayload]:
    """差分ノードとスコープ境界内の兄弟要素の部分木を収集する。

    スコープ境界ノード自身（scope_idx）は含まない。

    Args:
        tree: ASTノード列。
        action_index: 差分ノードのインデックス。
        scope_idx: スコープ境界ノードのインデックス。

    Returns:
        収集したノード payload のリスト（index 昇順）。
    """
    nodes_map: dict[int, NodePayload] = {}
    for root_idx in find_sibling_root_indices(tree, action_index, scope_idx):
        for idx, node in get_descendants(root_idx, tree):
            if idx != scope_idx:
                nodes_map[idx] = node_to_payload(idx, node)
    for idx, node in get_descendants(action_index, tree):
        if idx != scope_idx:
            nodes_map[idx] = node_to_payload(idx, node)
    return [nodes_map[i] for i in sorted(nodes_map)]


def _resolve_scope_idx(tree: list[ASTNode], action_index: int, scope_boundary: set[str]) -> int:
    """差分ノードのスコープ境界 index を解決する（必ず非 None を返す）。

    scope_boundary に該当する祖先が無い場合は最外祖先（root）、それも無ければ
    差分ノード自身を境界とする。これにより BLOCK_EXCLUDE_PARENT / BLOCK_INCLUDE_PARENT
    のスコープが常に確定し、下位粒度（Diff / BROTHER_DIFF）を包含できる。

    Args:
        tree: ASTノード列。
        action_index: 差分ノードのインデックス。
        scope_boundary: スコープ境界とみなすノード名の集合。

    Returns:
        スコープ境界ノードのインデックス。
    """
    scope_idx = find_scope_boundary_index(tree[action_index], tree, scope_boundary)
    if scope_idx is not None:
        return scope_idx
    node = tree[action_index]
    return node.parent[0] if node.parent else action_index


# ──────────────────────────────────────────────────────────
# スコープ切り出し（公開 API）
# cut_scope_*(ast, actions)  ← コア（任意の AST と actions を受け取る）
# base_scope_*(gum_diff)     ← base 側 shortcut
# head_scope_*(gum_diff)     ← head 側 shortcut
# ──────────────────────────────────────────────────────────


def cut_scope_diff(ast: AST, actions: list[GumAction]) -> dict[str, Any]:
    """差分ノードと配下ノード（DIFF）スコープを抽出する。

    Args:
        ast: 対象AST。
        actions: 差分アクション。

    Returns:
        {"per_action": [...], "merged": {"nodes": [...]}}
    """
    per_action: list[dict[str, Any]] = []
    merged_map: dict[int, NodePayload] = {}

    for block in cut_diff_blocks(ast, actions):
        nodes = sorted(
            [node_to_payload(idx, node) for idx, node in block.diff_block.items()],
            key=lambda x: x["origin_index"],
        )
        per_action.append(
            {
                "action_index": block.action_index,
                "action_name": block.action_name,
                "action_tree": block.action_tree,
                "nodes": nodes,
            }
        )
        for p in nodes:
            merged_map[p["origin_index"]] = p

    return {
        "per_action": per_action,
        "merged": {"nodes": [merged_map[i] for i in sorted(merged_map)]},
    }


def base_scope_diff(gum_diff: GumDiff) -> dict[str, Any]:
    """変更前(base)側の DIFF スコープを抽出する。"""
    return cut_scope_diff(gum_diff.base_ast, gum_diff.base_actions)


def head_scope_diff(gum_diff: GumDiff) -> dict[str, Any]:
    """変更後(head)側の DIFF スコープを抽出する。"""
    return cut_scope_diff(gum_diff.head_ast, gum_diff.head_actions)


def cut_scope_brother(ast: AST, actions: list[GumAction]) -> dict[str, Any]:
    """差分ノードの直接親の子孫ノード（BROTHER_DIFF）スコープを抽出する。

    Args:
        ast: 対象AST。
        actions: 差分アクション。

    Returns:
        {"per_action": [...], "merged": {"nodes": [...]}}
    """
    tree = ast.tree
    per_action: list[dict[str, Any]] = []
    merged_map: dict[int, NodePayload] = {}

    for action in actions:
        action_index = action.index
        parent_idx: int | None = None
        nodes: list[NodePayload] = []

        if action_index is not None and 0 <= action_index < len(tree):
            action_node = tree[action_index]
            if action_node.parent:
                parent_idx = action_node.parent[-1]
                for idx, node in enumerate(tree):
                    if node.parent and parent_idx in node.parent:
                        p = node_to_payload(idx, node)
                        nodes.append(p)
                        merged_map[idx] = p
            else:
                # 差分ノードがルート（直接親なし）のケース。Diff（自身＋子孫）と
                # 同じ集合を収集し、Diff ⊆ BROTHER_DIFF の包含を保証する。
                for idx, node in get_descendants(action_index, tree):
                    p = node_to_payload(idx, node)
                    nodes.append(p)
                    merged_map[idx] = p

        per_action.append(
            {
                "action_index": action_index,
                "action_name": action.action,
                "action_tree": action.tree,
                "parent_index": parent_idx,
                "nodes": nodes,
            }
        )

    return {
        "per_action": per_action,
        "merged": {"nodes": [merged_map[i] for i in sorted(merged_map)]},
    }


def base_scope_brother(gum_diff: GumDiff) -> dict[str, Any]:
    """変更前(base)側の BROTHER_DIFF スコープを抽出する。"""
    return cut_scope_brother(gum_diff.base_ast, gum_diff.base_actions)


def head_scope_brother(gum_diff: GumDiff) -> dict[str, Any]:
    """変更後(head)側の BROTHER_DIFF スコープを抽出する。"""
    return cut_scope_brother(gum_diff.head_ast, gum_diff.head_actions)


def cut_scope_block_exclude_parent(
    ast: AST,
    actions: list[GumAction],
    scope_boundary: set[str],
) -> dict[str, Any]:
    """スコープ境界内の兄弟+差分ノードの部分木（BLOCK_EXCLUDE_PARENT）を抽出する。

    スコープ境界ノード自身は含まない。

    Args:
        ast: 対象AST。
        actions: 差分アクション。
        scope_boundary: スコープ境界とみなすノード名の集合。

    Returns:
        {"per_action": [...], "merged": {"nodes": [...]}}
    """
    tree = ast.tree
    per_action: list[dict[str, Any]] = []
    merged_map: dict[int, NodePayload] = {}

    for action in actions:
        action_index = action.index
        scope_idx: int | None = None
        scope_name: str | None = None
        nodes: list[NodePayload] = []

        if action_index is not None and 0 <= action_index < len(tree):
            scope_idx = _resolve_scope_idx(tree, action_index, scope_boundary)
            scope_name = tree[scope_idx].name
            nodes = _collect_sibling_nodes(tree, action_index, scope_idx)
            for p in nodes:
                merged_map[p["origin_index"]] = p

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

    return {
        "per_action": per_action,
        "merged": {"nodes": [merged_map[i] for i in sorted(merged_map)]},
    }


def base_scope_block_exclude_parent(gum_diff: GumDiff, scope_boundary: set[str]) -> dict[str, Any]:
    """変更前(base)側の BLOCK_EXCLUDE_PARENT スコープを抽出する。"""
    return cut_scope_block_exclude_parent(gum_diff.base_ast, gum_diff.base_actions, scope_boundary)


def head_scope_block_exclude_parent(gum_diff: GumDiff, scope_boundary: set[str]) -> dict[str, Any]:
    """変更後(head)側の BLOCK_EXCLUDE_PARENT スコープを抽出する。"""
    return cut_scope_block_exclude_parent(gum_diff.head_ast, gum_diff.head_actions, scope_boundary)


def cut_scope_block_include_parent(
    ast: AST,
    actions: list[GumAction],
    scope_boundary: set[str],
) -> dict[str, Any]:
    """スコープ境界ノードの全子孫（BLOCK_INCLUDE_PARENT）を抽出する。

    スコープ境界ノード自身を含む。

    Args:
        ast: 対象AST。
        actions: 差分アクション。
        scope_boundary: スコープ境界とみなすノード名の集合。

    Returns:
        {"per_action": [...], "merged": {"nodes": [...]}}
    """
    tree = ast.tree
    per_action: list[dict[str, Any]] = []
    merged_map: dict[int, NodePayload] = {}

    for action in actions:
        action_index = action.index
        scope_idx: int | None = None
        scope_name: str | None = None
        nodes: list[NodePayload] = []

        if action_index is not None and 0 <= action_index < len(tree):
            scope_idx = _resolve_scope_idx(tree, action_index, scope_boundary)
            scope_name = tree[scope_idx].name
            nodes = [node_to_payload(idx, node) for idx, node in get_descendants(scope_idx, tree)]
            for p in nodes:
                merged_map[p["origin_index"]] = p

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

    return {
        "per_action": per_action,
        "merged": {"nodes": [merged_map[i] for i in sorted(merged_map)]},
    }


def base_scope_block_include_parent(gum_diff: GumDiff, scope_boundary: set[str]) -> dict[str, Any]:
    """変更前(base)側の BLOCK_INCLUDE_PARENT スコープを抽出する。"""
    return cut_scope_block_include_parent(gum_diff.base_ast, gum_diff.base_actions, scope_boundary)


def head_scope_block_include_parent(gum_diff: GumDiff, scope_boundary: set[str]) -> dict[str, Any]:
    """変更後(head)側の BLOCK_INCLUDE_PARENT スコープを抽出する。"""
    return cut_scope_block_include_parent(gum_diff.head_ast, gum_diff.head_actions, scope_boundary)
