"""差分ブロック抽出モジュール

GumTreeの差分解析結果から、差分ノードブロックを抽出する機能を提供
"""

import logging
from typing import Optional

from hayalab.classes.gumtree import AST, ASTNode, GumAction, GumDiff


def cut_diff_blocks(
    ast: AST,
    actions: list[GumAction],
    target_actions: Optional[list[str]] = None,
) -> list[dict]:
    """検出差分ノードブロックを元のASTから抽出

    Args:
        ast (AST): 対象のAST
        actions (list[GumAction]): 検出差分
        target_actions (Optional[list[str]]): 対象とするアクション名のリスト
            Noneの場合はすべてのアクションを対象とする

    Returns:
        list[dict]: 抽出された差分のアクションとそのノードブロック
            各要素は {"action": str, "diff_block": list[ASTNode]} の形式
    """
    ast_tree = ast.tree
    diff_blocks = []

    for action in actions:
        # 差分となったノード
        action_node = ast_tree[action.index]
        action_name = action.action
        diff_begin = action_node.begin
        diff_end = action_node.end
        action_parent = set(action_node.parent)
        action_parent.add(action.index)  # 自分自身を親とする要素を求めるため

        # ログ用
        base_idx = action.index
        logging.info(f"action:{base_idx} {action_name}")
        logging.info(f"action node: {action_node}")
        logging.info(f"  diff range: {diff_begin} - {diff_end}")

        # アクションの対象を絞る
        if target_actions is not None and action_name not in target_actions:
            logging.info("  skip this action")
            logging.info("")
            continue

        diff_block: list[ASTNode] = []
        diff_block.append(action_node)

        # 差分ノードをparentにもつ配下ノードをすべて抽出
        for node in ast_tree[action.index :]:
            if set(node.parent) >= action_parent:
                diff_block.append(node)
                # ログ
                base_idx = base_idx + 1
                logging.info("    " * len(set(node.parent) - action_parent) + f"  node:{base_idx} {node}")

        diff_blocks.append({"action": action.action, "diff_block": diff_block})

    logging.info("")
    return diff_blocks


def base_diff_blocks(
    gumtree_diff: GumDiff,
    target_actions: Optional[list[str]] = None,
) -> list[dict]:
    """GumDiffから変更前(base)側の差分ブロックを抽出

    Args:
        gumtree_diff (GumDiff): gumtree差分解析結果
        target_actions (Optional[list[str]]): 対象とするアクション名のリスト

    Returns:
        list[dict]: 抽出された差分のアクションとそのノードブロック
    """
    return cut_diff_blocks(
        gumtree_diff.base_ast,
        gumtree_diff.base_actions,
        target_actions,
    )


def head_diff_blocks(
    gumtree_diff: GumDiff,
    target_actions: Optional[list[str]] = None,
) -> list[dict]:
    """GumDiffから変更後(head)側の差分ブロックを抽出

    Args:
        gumtree_diff (GumDiff): gumtree差分解析結果
        target_actions (Optional[list[str]]): 対象とするアクション名のリスト

    Returns:
        list[dict]: 抽出された差分のアクションとそのノードブロック
    """
    return cut_diff_blocks(
        gumtree_diff.head_ast,
        gumtree_diff.head_actions,
        target_actions,
    )
