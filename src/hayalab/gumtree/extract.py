"""GumTree ASTからノードを収集する処理を提供するモジュール。"""

from __future__ import annotations

import logging

from hayalab.classes.gumtree import AST, ASTNode, GumAction, GumDiff


def cut_diff_blocks(
    ast: AST,
    actions: list[GumAction],
    target_actions: list[str] | None = None,
) -> list[ASTNode]:
    """差分アクションから対象ノード群を収集する。

    Args:
        ast (AST): 対象AST。
        actions (list[GumAction]): 差分アクション。
        target_actions (list[str] | None): 対象アクション名。

    Returns:
        list[ASTNode]: 元AST index 昇順の差分ノード群。
    """
    origin_ast_tree = ast.tree
    all_diff_nodes: dict[int, ASTNode] = {}

    for action in actions:
        if action.index is None or action.index < 0 or action.index >= len(origin_ast_tree):
            continue

        action_node = origin_ast_tree[action.index]
        action_name = action.action
        action_parent = set(action_node.parent)
        action_parent.add(action.index)

        logging.info(f"action:{action.index} {action_name}")
        logging.info(f"action node: {action_node}")
        logging.info(f"  diff range: {action_node.begin} - {action_node.end}")

        if target_actions is not None and action_name not in target_actions:
            logging.info("  skip this action")
            logging.info("")
            continue

        all_diff_nodes[action.index] = action_node

        if action_name.endswith("-tree"):
            base_idx = action.index
            for node in origin_ast_tree[action.index :]:
                if set(node.parent) >= action_parent:
                    base_idx += 1
                    all_diff_nodes[base_idx] = node
                    logging.info("    " * len(set(node.parent) - action_parent) + f"  node:{base_idx} {node}")

    logging.info("")
    return [all_diff_nodes[idx] for idx in sorted(all_diff_nodes)]


def base_diff_blocks(gumtree_diff: GumDiff, target_actions: list[str] | None = None) -> list[ASTNode]:
    """変更前(base)側ASTから差分ノード群を収集する。"""
    return cut_diff_blocks(gumtree_diff.base_ast, gumtree_diff.base_actions, target_actions)


def head_diff_blocks(gumtree_diff: GumDiff, target_actions: list[str] | None = None) -> list[ASTNode]:
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
    for index, node in enumerate(tree):
        if scope_idx in node.parent:
            descendants.append((index, node))
    return descendants
