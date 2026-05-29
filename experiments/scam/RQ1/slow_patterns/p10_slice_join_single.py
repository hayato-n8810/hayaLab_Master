"""Pattern 10: [].slice.call(...).join(...) の検出。

仕様:
  - outer call_expression の callee が member_expression で property == "join"
  - その member_expression.object が call_expression（inner）
    - その inner call_expression の callee が member_expression で property == "call"
    - さらにその member_expression.object が member_expression で property == "slice"
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
from .base import PatternMatch


class SliceJoinSingleMatcher:
    """Pattern 10: [].slice.call(...).join(...) を検出する matcher。"""

    pattern_id: int = 10
    pattern_name: str = "slice_join_single"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 10 を検出する。

        Args:
            nodes: base_ast.tree の ASTNode リスト。
            code: base_ast.code の文字列。
            mb_id: MBDiff レコードの id。

        Yields:
            PatternMatch（confidence=medium）。
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

            # member_expression.object が call_expression（inner）
            obj = get_member_object(nodes, callee)
            if obj is None or nodes[obj].name != "call_expression":
                continue

            # inner call: .call(...)
            inner_callee = get_call_callee(nodes, obj)
            if inner_callee is None or nodes[inner_callee].name != "member_expression":
                continue
            if get_member_property_name(nodes, inner_callee) != "call":
                continue

            # inner member_expression.object が member_expression で property == "slice"
            inner_obj = get_member_object(nodes, inner_callee)
            if inner_obj is None or nodes[inner_obj].name != "member_expression":
                continue
            if get_member_property_name(nodes, inner_obj) != "slice":
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
