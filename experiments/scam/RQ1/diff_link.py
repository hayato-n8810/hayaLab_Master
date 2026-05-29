"""Stage B: diff 連動フィルタ。

PatternMatch に対して base_actions / head_actions / head_nodes を参照し、
起点ノードが実際に fast 版で書き換えられているかを判定する。

判定ルール:
  base_covered（以下のいずれか）
    B1: base_actions の tree.index または ancestors.index が node_index に一致
    B2: base_actions のいずれかの tree.index が起点ノードの [begin, end) に含まれる

  head_covered:
    head_actions の subtree（action.index を起点とする部分木）配下に、論文の after に対応する
    head 側ノードが存在する。

最終判定: diff_linked = base_covered AND head_covered
"""

from __future__ import annotations

from dataclasses import replace

from hayalab.classes.gumtree import ASTNode, GumAction

from .ast_nav import (
    get_binary_rhs,
    get_call_callee,
    get_member_object,
    get_member_property_name,
    is_identifier,
    is_number_literal,
    named_children,
)
from .slow_patterns.base import PatternMatch

# ---------------------------------------------------------------------------
# 定数: pattern_id → head 側に期待される after ノードの name
# ---------------------------------------------------------------------------

_AFTER_KIND: dict[int, str | set[str]] = {
    1: "call_expression",  # Object.keys(...) の呼び出し（for ヘッダ内/外を問わない）
    2: {"subscript_expression"},  # str[i]
    3: "binary_expression",  # x + (string_literal | VAR_*)
    4: "call_expression",  # .empty()
    5: "call_expression",  # .charAt()
    6: "call_expression",  # .replace()
    7: "binary_expression",  # instanceof
    8: "binary_expression",  # & 1
    9: "for_statement",
    10: {"if_statement", "ternary_expression"},  # if 文 + ===/!== もしくは三項演算子 + ===/!==
}


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


def _binary_has_operator(nodes: list[ASTNode], bin_idx: int, op: str) -> bool:
    """binary_expression が指定の演算子を持つか確認する。

    Args:
        nodes: ASTNode のリスト。
        bin_idx: binary_expression ノードのインデックス。
        op: 期待する演算子の name。

    Returns:
        条件を満たせば True。
    """
    parent_path = nodes[bin_idx].parent + [bin_idx]
    for j in range(bin_idx + 1, len(nodes)):
        if nodes[j].parent == parent_path and nodes[j].name == op:
            return True
    return False


def _has_member_property(nodes: list[ASTNode], call_idx: int, prop_name: str) -> bool:
    """call_expression の callee が member_expression で指定 property を持つか確認する。

    Args:
        nodes: ASTNode のリスト。
        call_idx: call_expression ノードのインデックス。
        prop_name: 期待する property_identifier の value。

    Returns:
        条件を満たせば True。
    """
    parent_path = nodes[call_idx].parent + [call_idx]
    for j in range(call_idx + 1, len(nodes)):
        if nodes[j].parent != parent_path:
            continue
        if nodes[j].name != "member_expression":
            continue
        member_parent_path = nodes[j].parent + [j]
        for k in range(j + 1, len(nodes)):
            if nodes[k].parent == member_parent_path and nodes[k].name == "property_identifier":
                if nodes[k].value == prop_name:
                    return True
        break
    return False


def _is_object_keys_call(head_nodes: list[ASTNode], call_idx: int) -> bool:
    """call_expression が Object.keys(...) かを判定する。

    Args:
        head_nodes: head 側 ASTNode リスト。
        call_idx: call_expression のインデックス。

    Returns:
        Object.keys(...) なら True。
    """
    callee = get_call_callee(head_nodes, call_idx)
    if callee is None or head_nodes[callee].name != "member_expression":
        return False
    if get_member_property_name(head_nodes, callee) != "keys":
        return False
    obj = get_member_object(head_nodes, callee)
    if obj is None:
        return False
    return is_identifier(head_nodes, obj, "Object")


def _get_call_receiver_identifier(nodes: list[ASTNode], call_idx: int) -> str | None:
    """call_expression の receiver（member_expression.object）が identifier ならその value を返す。

    `obj.method(...)` の `obj` 部分が単純な identifier の場合のみ value を返す。
    `$(this).method(...)` 等の複雑な式の場合は None を返す。

    Args:
        nodes: ASTNode のリスト。
        call_idx: call_expression ノードのインデックス。

    Returns:
        identifier の value、識別できなければ None。
    """
    callee = get_call_callee(nodes, call_idx)
    if callee is None or nodes[callee].name != "member_expression":
        return None
    obj = get_member_object(nodes, callee)
    if obj is None:
        return None
    if nodes[obj].name != "identifier":
        return None
    return nodes[obj].value


def _binary_plus_with_string_or_var(head_nodes: list[ASTNode], bin_idx: int) -> bool:
    """binary_expression が "+" で、直 child のいずれかが string_literal または VAR_* identifier か判定する。

    Args:
        head_nodes: head 側 ASTNode リスト。
        bin_idx: binary_expression のインデックス。

    Returns:
        条件を満たせば True。
    """
    if not _binary_has_operator(head_nodes, bin_idx, "+"):
        return False
    parent_path = head_nodes[bin_idx].parent + [bin_idx]
    for j in range(bin_idx + 1, len(head_nodes)):
        if head_nodes[j].parent != parent_path:
            continue
        node = head_nodes[j]
        if node.name == "string_literal":
            return True
        if node.name == "identifier" and node.value.startswith("VAR_"):
            return True
    return False


def _if_has_eq_neq_in_condition(head_nodes: list[ASTNode], if_idx: int) -> bool:
    """if_statement の condition 配下に === / !== の binary_expression があるか判定する。

    Args:
        head_nodes: head 側 ASTNode リスト。
        if_idx: if_statement のインデックス。

    Returns:
        条件を満たせば True。
    """
    if_parent_path = head_nodes[if_idx].parent + [if_idx]
    for j in range(if_idx + 1, len(head_nodes)):
        node = head_nodes[j]
        # if_statement の子孫に限定
        if len(node.parent) < len(if_parent_path):
            break  # pre-order なので親パスより浅くなったら抜ける
        if node.parent[: len(if_parent_path)] != if_parent_path:
            break
        if node.name == "binary_expression":
            if _binary_has_operator(head_nodes, j, "===") or _binary_has_operator(head_nodes, j, "!=="):
                return True
    return False


def _ternary_has_eq_neq_in_condition(head_nodes: list[ASTNode], ternary_idx: int) -> bool:
    """ternary_expression の condition が === / !== の binary_expression か判定する。

    `cond ? x : y` の cond 部分（最初の named child）を取り出し、binary_expression で
    === または !== の演算子を持つかを確認する。

    Args:
        head_nodes: head 側 ASTNode リスト。
        ternary_idx: ternary_expression のインデックス。

    Returns:
        condition が === / !== の binary_expression なら True。
    """
    children = named_children(head_nodes, ternary_idx)
    if not children:
        return False
    cond_idx = children[0]
    if head_nodes[cond_idx].name != "binary_expression":
        return False
    return _binary_has_operator(head_nodes, cond_idx, "===") or _binary_has_operator(head_nodes, cond_idx, "!==")


def _head_matches_after_for_pattern(
    pattern_id: int,
    head_node: ASTNode,
    head_nodes: list[ASTNode],
    head_idx: int,
    base_nodes: list[ASTNode] | None = None,
    base_node_index: int | None = None,
) -> bool:
    """Head 側ノードが論文の after パターンに対応するかを判定する。

    Args:
        pattern_id: パターン番号（1〜10）。
        head_node: head 側の候補ノード。
        head_nodes: head 側の全 ASTNode リスト。
        head_idx: head 側の候補ノードインデックス。
        base_nodes: base 側 ASTNode リスト（任意、ID4 の receiver 比較で使用）。
        base_node_index: base 側起点ノード（PatternMatch.node_index）。

    Returns:
        after パターンに対応すれば True。
    """
    expected = _AFTER_KIND.get(pattern_id)
    if expected is None:
        return False

    expected_set = {expected} if isinstance(expected, str) else expected
    if head_node.name not in expected_set:
        return False

    if pattern_id == 1:
        # head_node は call_expression。Object.keys(...) か確認する。
        return _is_object_keys_call(head_nodes, head_idx)

    if pattern_id == 2:
        # subscript_expression で object が identifier / member_expression / call_expression
        parent_path = head_nodes[head_idx].parent + [head_idx]
        for j in range(head_idx + 1, len(head_nodes)):
            if head_nodes[j].parent != parent_path:
                continue
            if head_nodes[j].name == "object":
                if j + 1 >= len(head_nodes):
                    return False
                return head_nodes[j + 1].name in {"identifier", "member_expression", "call_expression"}
        return False

    if pattern_id == 3:
        # x + (string_literal | VAR_* identifier)
        return _binary_plus_with_string_or_var(head_nodes, head_idx)

    if pattern_id == 4:
        if not _has_member_property(head_nodes, head_idx, "empty"):
            return False
        # receiver 同一性チェック（base_nodes 未指定 / 識別不能なら緩く True を返す）
        if base_nodes is None or base_node_index is None:
            return True
        base_recv = _get_call_receiver_identifier(base_nodes, base_node_index)
        head_recv = _get_call_receiver_identifier(head_nodes, head_idx)
        if base_recv is None or head_recv is None:
            return True
        return base_recv == head_recv

    if pattern_id == 5:
        return _has_member_property(head_nodes, head_idx, "charAt")

    if pattern_id == 6:
        return _has_member_property(head_nodes, head_idx, "replace")

    if pattern_id == 7:
        return _binary_has_operator(head_nodes, head_idx, "instanceof")

    if pattern_id == 8:
        # & 1 を要求（rhs が number:1）
        if not _binary_has_operator(head_nodes, head_idx, "&"):
            return False
        rhs = get_binary_rhs(head_nodes, head_idx)
        if rhs is None:
            return False
        return is_number_literal(head_nodes, rhs, "1")

    if pattern_id == 9:
        # 9 は for_statement のみ要求。追加条件は今のところ無し。
        return True

    if pattern_id == 10:
        # if_statement: condition 配下に === / !==
        # ternary_expression: condition が === / !==
        if head_node.name == "if_statement":
            return _if_has_eq_neq_in_condition(head_nodes, head_idx)
        if head_node.name == "ternary_expression":
            return _ternary_has_eq_neq_in_condition(head_nodes, head_idx)
        return False

    return True


def _resolve_action_node_index(action: GumAction) -> int | None:
    """GumAction が指す head ノードのインデックスを解決する。

    Args:
        action: GumAction（head_actions の要素）。

    Returns:
        ノードインデックス。解決できなければ None。
    """
    if action.index is not None:
        return action.index
    if action.ancestors:
        # ancestors の最初の要素を起点とみなす（祖先で代替）
        return action.ancestors[0].index
    return None


def _is_descendant_or_self(head_nodes: list[ASTNode], action_idx: int, h_idx: int) -> bool:
    """h_idx が action_idx の subtree（自身を含む）に属するか判定する。

    parent パスは「ルートからの親インデックス列」。action_idx が h_idx の祖先か
    自身であれば True。

    Args:
        head_nodes: head 側 ASTNode リスト。
        action_idx: 起点ノードインデックス。
        h_idx: 判定対象ノードインデックス。

    Returns:
        h_idx が action_idx の subtree 内なら True。
    """
    if action_idx == h_idx:
        return True
    if action_idx < 0 or action_idx >= len(head_nodes):
        return False
    if h_idx < 0 or h_idx >= len(head_nodes):
        return False
    return action_idx in head_nodes[h_idx].parent


# ---------------------------------------------------------------------------
# Stage A フィルタ: base_covered 判定
# ---------------------------------------------------------------------------


def is_base_covered(pm: PatternMatch, base_actions: list[GumAction]) -> bool:
    """PatternMatch が base_actions の subtree に含まれるかを判定する。

    B1: base_actions のいずれかの action.index == node_index、または
        action.ancestors のいずれかが node_index に一致する。
    B2: base_actions のいずれかの action.index が [begin, end) に含まれる。

    いずれかを満たせば True。

    Args:
        pm: Stage A で生成された PatternMatch。
        base_actions: GumDiff.base_actions（GumAction のリスト）。

    Returns:
        base_covered が True なら True。
    """
    node_index = pm.node_index
    begin = pm.begin
    end = pm.end

    # B1
    for action in base_actions:
        if action.index == node_index:
            return True
        if action.ancestors and any(anc.index == node_index for anc in action.ancestors):
            return True

    # B2
    for action in base_actions:
        if action.index is not None and begin <= action.index < end:
            return True

    return False


# ---------------------------------------------------------------------------
# Stage B エントリポイント
# ---------------------------------------------------------------------------


def apply_diff_link(
    match: PatternMatch,
    base_actions: list[GumAction],
    head_actions: list[GumAction],
    matches: list[tuple[int, int]],
    head_nodes: list[ASTNode],
    base_nodes: list[ASTNode] | None = None,
) -> PatternMatch:
    """PatternMatch に diff_linked / diff_reason を付与して返す。

    判定:
      base_covered = B1 OR B2（base_actions ベース）
      head_covered = head_actions の subtree 内に after パターン候補が存在する
      diff_linked  = base_covered AND head_covered

    Args:
        match: Stage A で生成された PatternMatch。
        base_actions: GumDiff.base_actions（GumAction のリスト）。
        head_actions: GumDiff.head_actions（GumAction のリスト）。
        matches: GumDiff.matches（API 互換のため受け取るが内部判定では未使用）。
        head_nodes: GumDiff.head_ast.tree（ASTNode のリスト）。
        base_nodes: GumDiff.base_ast.tree（ASTNode のリスト）。
            ID4 の receiver 同一性チェック等、base 側との照合が必要なパターンで使用する。

    Returns:
        diff_linked / diff_reason が更新された PatternMatch（frozen dataclass なので新規作成）。
    """
    del matches  # 方針 B では未使用（API 互換のため引数は残す）

    node_index = match.node_index
    begin = match.begin
    end = match.end

    # ---- base 側 ----
    b1_met = False
    b2_met = False

    for action in base_actions:
        if action.index == node_index:
            b1_met = True
            break
        if action.ancestors and any(anc.index == node_index for anc in action.ancestors):
            b1_met = True
            break

    for action in base_actions:
        if action.index is not None and begin <= action.index < end:
            b2_met = True
            break

    base_covered = b1_met or b2_met

    # ---- head 側 ----
    head_covered = False

    if base_covered and head_actions and head_nodes:
        # head_actions が指す起点ノードインデックスを集める
        action_roots: list[int] = []
        for action in head_actions:
            root = _resolve_action_node_index(action)
            if root is None:
                continue
            if 0 <= root < len(head_nodes):
                action_roots.append(root)

        if action_roots:
            # 各 head ノードを走査し、いずれかの action subtree に属し、
            # かつ after パターンを満たすなら head_covered = True
            for h_idx in range(len(head_nodes)):
                if not any(_is_descendant_or_self(head_nodes, root, h_idx) for root in action_roots):
                    continue
                if _head_matches_after_for_pattern(
                    match.pattern_id,
                    head_nodes[h_idx],
                    head_nodes,
                    h_idx,
                    base_nodes=base_nodes,
                    base_node_index=node_index,
                ):
                    head_covered = True
                    break

    if not (base_covered and head_covered):
        return match

    base_label = "B1" if b1_met else "B2"
    diff_reason = f"base_{base_label}_head_action"

    return replace(match, diff_linked=True, diff_reason=diff_reason)
