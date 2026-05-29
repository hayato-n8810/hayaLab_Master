"""Pattern 5: substr(0, N) ==|=== str による先頭比較の検出。

仕様:
  - binary_expression で operator ∈ {==, ===, !=, !==}
  - lhs/rhs のどちらかが call_expression で .substr を呼び出し、
    引数が 2 個で args[0] == number:0、args[1] == number で int(value) > 0
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    get_binary_operator,
    get_call_arguments,
    get_call_callee,
    get_member_property_name,
    is_number_literal,
    match_either,
    walk_pre,
)
from .base import PatternMatch

_CMP_OPS: frozenset[str] = frozenset({"==", "===", "!=", "!=="})


def _is_substr_prefix_call(nodes: list[ASTNode], idx: int) -> bool:
    """call_expression が .substr(0, N) で N > 0 の形かどうかを判定する。

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
    if get_member_property_name(nodes, callee) != "substr":
        return False
    args = get_call_arguments(nodes, idx)
    if len(args) != 2:
        return False
    if not is_number_literal(nodes, args[0], "0"):
        return False
    # args[1] は number で int(value) > 0
    if nodes[args[1]].name != "number":
        return False
    try:
        return int(nodes[args[1]].value) > 0
    except (ValueError, TypeError):
        return False


def _is_any_expr(nodes: list[ASTNode], idx: int) -> bool:
    """任意の式ノードか（右辺には何でも来る）。

    Args:
        nodes: ASTNode のリスト（未使用）。
        idx: チェック対象ノードのインデックス（未使用）。

    Returns:
        常に True。
    """
    return True


class SubstrPrefixCmpMatcher:
    """Pattern 5: substr(0, N) ==|=== str による先頭比較を検出する matcher。"""

    pattern_id: int = 5
    pattern_name: str = "substr_prefix_cmp"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 5 を検出する。

        Args:
            nodes: base_ast.tree の ASTNode リスト。
            code: base_ast.code の文字列。
            mb_id: MBDiff レコードの id。

        Yields:
            PatternMatch（confidence=high）。
        """
        for idx in walk_pre(nodes):
            if nodes[idx].name != "binary_expression":
                continue

            op = get_binary_operator(nodes, idx)
            if op not in _CMP_OPS:
                continue

            result = match_either(nodes, idx, _is_substr_prefix_call, _is_any_expr)
            if result is None:
                continue

            begin = nodes[idx].begin
            end = nodes[idx].end
            snippet = code[begin:end][:200]
            yield PatternMatch(
                mb_id=mb_id,
                side="base",
                pattern_id=self.pattern_id,
                confidence="high",
                node_index=idx,
                begin=begin,
                end=end,
                snippet=snippet,
            )
