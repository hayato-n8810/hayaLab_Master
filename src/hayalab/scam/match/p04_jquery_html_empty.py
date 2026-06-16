"""Pattern 4: jQuery html('') の検出。

仕様: call_expression で callee が .html の member_expression、
      引数が 1 個で空文字列リテラルのもの。
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    get_call_arguments,
    get_call_callee,
    get_member_property_name,
    is_empty_string_literal,
    walk_pre,
)
from .base import PatternMatch, make_pattern_match


class JQueryHtmlEmptyMatcher:
    """Pattern 4: jQuery html('') を検出する matcher。"""

    pattern_id: int = 4
    pattern_name: str = "jquery_html_empty"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 4 を検出する。

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
            if get_member_property_name(nodes, callee) != "html":
                continue

            args = get_call_arguments(nodes, idx)
            if len(args) != 1:
                continue
            if nodes[args[0]].name != "string":
                continue
            if not is_empty_string_literal(nodes, args[0]):
                continue

            yield make_pattern_match(nodes, idx, code, mb_id=mb_id, pattern_id=self.pattern_id, confidence="high")
