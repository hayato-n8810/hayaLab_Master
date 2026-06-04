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


def find_sibling_root_indices(
    tree: list[ASTNode],
    action_index: int,
    scope_idx: int,
) -> list[int]:
    """差分ノードと同じスコープ直下の兄弟ルートインデックスを返す。

    差分ノードの parent チェーン内で scope_idx の一つ下の階層を特定し、
    そのノードを直接親に持つノードを兄弟ルートとして返す。

    Args:
        tree: ASTノード列。
        action_index: 差分ノードのインデックス。
        scope_idx: スコープ境界ノードのインデックス。

    Returns:
        兄弟ルートノードのインデックスリスト（昇順）。
    """
    if action_index == scope_idx:
        return []
    action_node = tree[action_index]
    if not action_node.parent:
        return []
    scope = action_node.parent.index(scope_idx)
    if scope + 1 < len(action_node.parent):
        parent_idx = action_node.parent[scope + 1]
    else:
        # 差分ノードがスコープ境界の直接の子のケース。scope_idx の一つ下の
        # 階層が存在しないため、scope_idx 直下の同階層ノードを兄弟ルートとして扱う。
        # これにより BLOCK_EXCLUDE_PARENT が BROTHER_DIFF（直接親 = scope_idx の
        # 全子孫）を包含し、粒度間の単調性が保たれる。
        parent_idx = scope_idx
    if not (0 <= parent_idx < len(tree)):
        return []
    return sorted(idx for idx, node in enumerate(tree) if node.parent and node.parent[-1] == parent_idx and scope_idx in node.parent)
