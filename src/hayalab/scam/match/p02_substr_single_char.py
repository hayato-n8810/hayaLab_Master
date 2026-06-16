"""Pattern 2: substr(i, 1) による 1 文字抽出の検出。

仕様: call_expression で callee が .substr の member_expression、
      引数が 2 個で 2 番目が number: 1 であるもの。
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    get_call_arguments,
    get_call_callee,
    get_member_property_name,
    is_number_literal,
    walk_pre,
)
from .base import PatternMatch, make_pattern_match


class SubstrSingleCharMatcher:
    """Pattern 2: substr(i, 1) による 1 文字抽出を検出する matcher。"""

    pattern_id: int = 2
    pattern_name: str = "substr_single_char"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 2 を検出する。

        Args:
            nodes: base_ast.tree の ASTNode リスト。
            code: base_ast.code の文字列。
            mb_id: MBDiff レコードの id。

        Yields:
            PatternMatch（1 件ずつ）。
        """
        for idx in walk_pre(nodes):
            if nodes[idx].name != "call_expression":
                continue

            callee = get_call_callee(nodes, idx)
            if callee is None:
                continue
            if nodes[callee].name != "member_expression":
                continue
            if get_member_property_name(nodes, callee) != "substr":
                continue

            args = get_call_arguments(nodes, idx)
            if len(args) != 2:
                continue
            if not is_number_literal(nodes, args[1], "1"):
                continue

            yield make_pattern_match(nodes, idx, code, mb_id=mb_id, pattern_id=self.pattern_id, confidence="high")
