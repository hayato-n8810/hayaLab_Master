"""GumTree ASTを走査する処理を提供するモジュール。"""

from __future__ import annotations

from hayalab.classes.gumtree import AST, ASTNode


def count_label(ast: AST, label_list: list[str]) -> dict[str, int]:
    """AST中の指定ノード名の出現回数を数える。

    Args:
        ast (AST): 対象AST。
        label_list (list[str]): 集計対象のノード名。

    Returns:
        dict[str, int]: ノード名ごとの出現回数。
    """
    label_count = {label: 0 for label in label_list}
    for node in ast.tree:
        if node.name in label_count:
            label_count[node.name] += 1
    return label_count


def collect_method_name(ast: AST) -> list[str]:
    """ASTから property_identifier ノードの値を収集する。

    Args:
        ast (AST): 対象AST。

    Returns:
        list[str]: 収集したメソッド名。
    """
    methods: list[str] = []
    for node in ast.tree:
        if node.name == "property_identifier":
            methods.append(node.value)
    return methods


def find_scope_boundary_index(
    node: ASTNode,
    tree: list[ASTNode],
    scope_boundary: set[str],
) -> int | None:
    """差分ノードから最も近いスコープ境界ノード index を取得する。

    Args:
        node (ASTNode): 探索対象ノード。
        tree (list[ASTNode]): ASTノード列。
        scope_boundary (set[str]): スコープ境界ノード名の集合。

    Returns:
        int | None: 見つかったスコープ境界 index。見つからない場合は None。
    """
    for parent_idx in reversed(node.parent):
        if tree[parent_idx].name in scope_boundary:
            return parent_idx
    return None
