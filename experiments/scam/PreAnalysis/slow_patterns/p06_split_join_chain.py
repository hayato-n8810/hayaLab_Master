"""Pattern 6: split(...).join(...) チェーンの検出。

仕様:
  - call_expression で callee が member_expression で property == "join"
  - その member_expression.object が call_expression で callee が member_expression
    で property == "split"
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    get_call_callee,
    get_member_object,
    get_member_property_name,
    walk_pre,
)
from .base import PatternMatch, make_pattern_match


class SplitJoinChainMatcher:
    """Pattern 6: split().join() チェーンを検出する matcher。"""

    pattern_id: int = 6
    pattern_name: str = "split_join_chain"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 6 を検出する。

        Args:
            nodes: base_ast.tree の ASTNode リスト。
            code: base_ast.code の文字列。
            mb_id: MBDiff レコードの id。

        Yields:
            PatternMatch（confidence=high）。
        """
        for idx in walk_pre(nodes):
            if nodes[idx].name != "call_expression":
                continue

            # outer: .join(...)
            callee = get_call_callee(nodes, idx)
            if callee is None or nodes[callee].name != "member_expression":
                continue
            if get_member_property_name(nodes, callee) != "join":
                continue

            # member_expression.object が call_expression
            obj = get_member_object(nodes, callee)
            if obj is None or nodes[obj].name != "call_expression":
                continue

            # inner: .split(...)
            inner_callee = get_call_callee(nodes, obj)
            if inner_callee is None or nodes[inner_callee].name != "member_expression":
                continue
            if get_member_property_name(nodes, inner_callee) != "split":
                continue

            yield make_pattern_match(nodes, idx, code, mb_id=mb_id, pattern_id=self.pattern_id, confidence="high")
