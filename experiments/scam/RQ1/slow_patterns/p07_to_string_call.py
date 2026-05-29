"""Pattern 7: toString.call(x) ==|=== "[object ...]" の検出。

仕様:
  - binary_expression で operator ∈ {==, ===}
  - lhs/rhs のどちらかが:
      call_expression で callee が member_expression
      - member_expression.object が identifier で value == "toString"
      - member_expression の property_identifier.value == "call"
  - もう一方が string で string_fragment.value が "[object" で始まる
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    direct_children,
    find_first_child,
    get_binary_operator,
    get_call_callee,
    get_member_object,
    get_member_property_name,
    is_identifier,
    match_either,
    walk_pre,
)
from .base import PatternMatch

_EQ_OPS: frozenset[str] = frozenset({"==", "==="})


def _is_to_string_call_expr(nodes: list[ASTNode], idx: int) -> bool:
    """call_expression が toString.call(...) の形かどうかを判定する。

    Args:
        nodes: ASTNode のリスト。
        idx: チェック対象ノードのインデックス。

    Returns:
        条件を満たせば True。
    """
    if nodes[idx].name != "call_expression":
        return False
    callee = get_call_callee(nodes, idx)
    if callee is None or nodes[callee].name != "member_expression":
        return False
    if get_member_property_name(nodes, callee) != "call":
        return False
    obj = get_member_object(nodes, callee)
    if obj is None:
        return False
    return is_identifier(nodes, obj, "toString")


def _is_object_type_string(nodes: list[ASTNode], idx: int) -> bool:
    """String ノードで string_fragment.value が "[object" で始まるかを判定する。

    Args:
        nodes: ASTNode のリスト。
        idx: チェック対象ノードのインデックス。

    Returns:
        条件を満たせば True。
    """
    if nodes[idx].name != "string":
        return False
    frag = find_first_child(nodes, idx, "string_fragment")
    if frag is None:
        return False
    return nodes[frag].value.startswith("[object")


class ToStringCallMatcher:
    """Pattern 7: toString.call(x) ==|=== "[object ...]" を検出する matcher。

    NOTE: 信頼度は medium（toString が組込みか不明なため）。
    """

    pattern_id: int = 7
    pattern_name: str = "to_string_call"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 7 を検出する。

        Args:
            nodes: base_ast.tree の ASTNode リスト。
            code: base_ast.code の文字列。
            mb_id: MBDiff レコードの id。

        Yields:
            PatternMatch（confidence=medium）。
        """
        for idx in walk_pre(nodes):
            if nodes[idx].name != "binary_expression":
                continue

            op = get_binary_operator(nodes, idx)
            if op not in _EQ_OPS:
                continue

            result = match_either(nodes, idx, _is_to_string_call_expr, _is_object_type_string)
            if result is None:
                continue

            begin = nodes[idx].begin
            end = nodes[idx].end
            snippet = code[begin:end][:200]
            yield PatternMatch(
                mb_id=mb_id,
                side="base",
                pattern_id=self.pattern_id,
                confidence="medium",
                node_index=idx,
                begin=begin,
                end=end,
                snippet=snippet,
            )


def _unused_import_guard() -> None:
    """使用されていないインポートを回避するためのダミー関数。"""
    _ = direct_children
