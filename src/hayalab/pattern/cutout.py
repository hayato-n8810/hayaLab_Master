"""パターン抽出パイプライン Stage 1: 切り出し (L1, L2, L3, L4)。

GumTree 差分 (`GumDiff`) と depth (1..4) を受け取り、差分ノード集合を含む部分木を
`Cutout` として返す。複数の差分アクションが同一の根ノードに収束する場合は統合する。

公開 API:
    - cut_diff(diff, depth): list[Cutout]
"""

from __future__ import annotations

from hayalab.classes.gumtree import AST, ASTNode, GumDiff
from hayalab.classes.pattern import Cutout
from hayalab.config.pattern_config import SCOPE_BOUNDARY


def _action_diff_indices(tree: list[ASTNode], action_index: int) -> set[int]:
    """差分アクションの根ノードとその子孫の index 集合を返す。

    根とするノードの index `action_index` について、対象ノード j が部分木に含まれるのは
    j == action_index または action_index ∈ tree[j].parent のとき。

    Args:
        tree: 元 AST のノード列。
        action_index: 差分アクションの根ノード index。

    Returns:
        差分ノード index の set。範囲外なら空集合。
    """
    if not (0 <= action_index < len(tree)):
        return set()
    indices: set[int] = {action_index}
    for j, node in enumerate(tree):
        if action_index in node.parent:
            indices.add(j)
    return indices


def _subtree_indices(tree: list[ASTNode], root_index: int) -> list[int]:
    """根ノードを含む部分木の index 列を昇順で返す。

    Args:
        tree: 元 AST のノード列。
        root_index: 部分木の根 index。

    Returns:
        昇順ソートされた index リスト（root 自身を含む）。
    """
    if not (0 <= root_index < len(tree)):
        return []
    indices = [root_index]
    for j, node in enumerate(tree):
        if root_index in node.parent:
            indices.append(j)
    return sorted(indices)


def _determine_root_index(
    tree: list[ASTNode],
    diff_index: int,
    depth: int,
    scope_boundary: set[str],
) -> int:
    """Depth ごとに切り出し根ノード index を決定する。

    L1: diff_index 自身。
    L2: diff_index の親 (parent[-1])。 diff_index が root の場合は diff_index 自身。
    L3: diff_index から親方向に遡り、最初に scope_boundary を満たすノード s の
        直接の子で diff_index の祖先である最上位ノード（diff_index が s の直接の子なら diff_index）。
    L4: s 自身。

    Args:
        tree: 元 AST のノード列。
        diff_index: 差分ノードの index。
        depth: 切り出し depth (1..4)。
        scope_boundary: スコープ境界とみなすノード名集合。

    Returns:
        切り出し根ノード index。
    """
    node = tree[diff_index]
    parents = node.parent  # 根からのパス（祖先 index 列）

    if depth == 1:
        return diff_index

    if depth == 2:
        if parents:
            return parents[-1]
        return diff_index

    # L3 / L4: 親方向を逆順に走査してスコープ境界 s を探す
    s_pos_in_parents: int | None = None
    for pos in range(len(parents) - 1, -1, -1):
        anc_idx = parents[pos]
        if tree[anc_idx].name in scope_boundary:
            s_pos_in_parents = pos
            break

    # diff_index 自身がスコープ境界に該当する場合
    if s_pos_in_parents is None and node.name in scope_boundary:
        # L3 = L4 = diff_index 自身
        return diff_index

    if s_pos_in_parents is None:
        # スコープ境界が見つからない: フォールバックとして L4 → root（parent[0]）、L3 → diff_index
        if depth == 4 and parents:
            return parents[0]
        return diff_index

    s_idx = parents[s_pos_in_parents]
    if depth == 4:
        return s_idx

    # L3: s の直接の子で diff_index の祖先である最上位ノード
    if s_pos_in_parents == len(parents) - 1:
        # diff_index が s の直接の子
        return diff_index
    return parents[s_pos_in_parents + 1]


def cut_diff(diff: GumDiff, depth: int) -> list[Cutout]:
    """差分から depth レベルの切り出し集合を返す。

    差分アクションの種別 (delete-tree / insert-tree / move-tree / update-node) を
    問わず、`action.index` を根とする部分木全体を差分ノード集合 Δ に追加する。

    Args:
        diff: GumTree 差分。base_actions を使用（slow 側）。
        depth: 切り出し depth (1..4)。

    Returns:
        差分ノード群を統合した Cutout のリスト。根ノードが重複したら統合される。

    Raises:
        ValueError: depth が 1..4 の範囲外。
    """
    if depth not in (1, 2, 3, 4):
        raise ValueError(f"depth must be one of 1..4, got {depth}")

    ast: AST = diff.base_ast
    tree = ast.tree
    mb_id_attr = getattr(diff, "id", None)
    # GumDiff には id がないため、呼び出し側で必要なら Cutout.mb_id を上書きする
    mb_id = mb_id_attr if isinstance(mb_id_attr, int) else -1

    # 各 action ごとに diff index 集合と root_index を計算
    # root_index → (diff_indices set, all subtree indices) でマージする
    root_to_diff: dict[int, set[int]] = {}

    for action in diff.base_actions:
        if action.index is None:
            continue
        action_idx = action.index
        if not (0 <= action_idx < len(tree)):
            continue

        diff_indices = _action_diff_indices(tree, action_idx)
        root_idx = _determine_root_index(tree, action_idx, depth, SCOPE_BOUNDARY)

        if root_idx in root_to_diff:
            root_to_diff[root_idx] |= diff_indices
        else:
            root_to_diff[root_idx] = set(diff_indices)

    cutouts: list[Cutout] = []
    for root_idx in sorted(root_to_diff.keys()):
        node_indices = _subtree_indices(tree, root_idx)
        # 差分ノードのうち実際に部分木に含まれるもののみを保持
        diff_in_subtree = {i for i in root_to_diff[root_idx] if i in node_indices}
        cutouts.append(
            Cutout(
                mb_id=mb_id,
                depth=depth,
                root_index=root_idx,
                node_indices=node_indices,
                diff_node_indices=diff_in_subtree,
            )
        )
    return cutouts


def cut_diff_all_depths(
    diff: GumDiff,
    mb_id: int,
    depths: tuple[int, ...] = (1, 2, 3, 4),
) -> dict[int, list[Cutout]]:
    """差分から指定 depth 集合の Cutout を一括生成し、`{depth: [Cutout, ...]}` を返す。

    各 Cutout には呼び出し側が指定した `mb_id` がセットされる。
    `cut_diff` の `mb_id = -1` フォールバックを廃止する経路として、本 API を推奨する。

    Args:
        diff: GumTree 差分。
        mb_id: 中間表現に書き込む MB の一貫識別子。
        depths: 生成対象の depth 集合（既定: (1, 2, 3, 4)）。

    Returns:
        depth ごとの Cutout リスト。各 Cutout の `mb_id` は引数で指定された値。

    Raises:
        ValueError: depths のいずれかが 1..4 の範囲外。
    """
    result: dict[int, list[Cutout]] = {}
    for depth in depths:
        cutouts = cut_diff(diff, depth)
        result[depth] = [c.model_copy(update={"mb_id": mb_id}) for c in cutouts]
    return result
