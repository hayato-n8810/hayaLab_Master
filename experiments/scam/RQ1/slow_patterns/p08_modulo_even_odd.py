"""Pattern 8: n % 2 ==|=== 0|1 による偶奇判定の検出。

仕様:
  - binary_expression で operator ∈ {==, ===}
  - lhs/rhs の一方が binary_expression で operator == "%" かつ rhs が number:2
  - もう一方が number で value ∈ {"0", "1"}
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    get_binary_lhs,
    get_binary_operator,
    get_binary_rhs,
    is_number_literal,
    match_either,
    walk_pre,
)
from .base import PatternMatch

_EQ_OPS: frozenset[str] = frozenset({"==", "==="})


def _is_modulo_2_expr(nodes: list[ASTNode], idx: int) -> bool:
    """binary_expression が (expr % 2) の形かどうかを判定する。

    Args:
        nodes: ASTNode のリスト。
        idx: チェック対象ノードのインデックス。

    Returns:
        条件を満たせば True。
    """
    if nodes[idx].name != "binary_expression":
        return False
    if get_binary_operator(nodes, idx) != "%":
        return False
    rhs = get_binary_rhs(nodes, idx)
    if rhs is None:
        return False
    return is_number_literal(nodes, rhs, "2")


def _is_zero_or_one(nodes: list[ASTNode], idx: int) -> bool:
    """Number ノードで value が "0" または "1" かを判定する。

    Args:
        nodes: ASTNode のリスト。
        idx: チェック対象ノードのインデックス。

    Returns:
        条件を満たせば True。
    """
    return is_number_literal(nodes, idx, {"0", "1"})


class ModuloEvenOddMatcher:
    """Pattern 8: n % 2 ==|=== 0|1 による偶奇判定を検出する matcher。"""

    pattern_id: int = 8
    pattern_name: str = "modulo_even_odd"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 8 を検出する。

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
            if op not in _EQ_OPS:
                continue

            result = match_either(nodes, idx, _is_modulo_2_expr, _is_zero_or_one)
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


def _unused_import_guard() -> None:
    """使用されていないインポートを回避するためのダミー関数。"""
    _ = get_binary_lhs
