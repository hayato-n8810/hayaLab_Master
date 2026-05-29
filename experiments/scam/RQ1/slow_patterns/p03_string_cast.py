"""Pattern 3: String(x) による型変換の検出。

仕様: call_expression で callee が identifier: String、引数が 1 個のもの。
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    get_call_arguments,
    get_call_callee,
    is_identifier,
    walk_pre,
)
from .base import PatternMatch


class StringCastMatcher:
    """Pattern 3: String(x) による型変換を検出する matcher。"""

    pattern_id: int = 3
    pattern_name: str = "string_cast"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 3 を検出する。

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
            if not is_identifier(nodes, callee, "String"):
                continue

            args = get_call_arguments(nodes, idx)
            if len(args) != 1:
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
