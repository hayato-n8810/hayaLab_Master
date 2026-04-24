"""GumTree ASTからノードを収集する処理を提供するモジュール。"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import AST, ActionBlock, ASTNode, GumAction, GumDiff


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
