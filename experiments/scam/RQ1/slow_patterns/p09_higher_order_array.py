"""Pattern 9: 高階関数（reduce/forEach/map/filter）+ コールバックの検出。

仕様: call_expression で callee が reduce/forEach/map/filter の member_expression、
      arguments に function/function_expression/arrow_function を 1 つ以上含むもの。
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    get_call_arguments,
    get_call_callee,
    get_member_property_name,
    walk_pre,
)
from .base import PatternMatch

# TODO: reduce/forEach/map/filter 以外も追加するか？ some/every/find なども高階関数の可能性があるが、信頼度はさらに下がるため要注意
# _HIGHER_ORDER_METHODS: frozenset[str] = frozenset({"forEach", "map", "flatMap", "reduce", "reduceRight", "filter", "find", "findIndex", "findLastIndex", "findLast", "some", "every"})
_HIGHER_ORDER_METHODS: frozenset[str] = frozenset({"reduce"})

_CALLBACK_NODE_NAMES: frozenset[str] = frozenset({"function", "function_expression", "arrow_function"})


class HigherOrderArrayMatcher:
    """Pattern 9: 高階関数 + コールバックを検出する matcher。

    NOTE: 信頼度は low。単独では false positive が多いため diff 連動フィルタ必須。
    """

    pattern_id: int = 9
    pattern_name: str = "higher_order_array"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 9 を検出する。

        Args:
            nodes: base_ast.tree の ASTNode リスト。
            code: base_ast.code の文字列。
            mb_id: MBDiff レコードの id。

        Yields:
            PatternMatch（1 件ずつ、confidence=low）。
        """
        for idx in walk_pre(nodes):
            if nodes[idx].name != "call_expression":
                continue

            callee = get_call_callee(nodes, idx)
            if callee is None:
                continue
            if nodes[callee].name != "member_expression":
                continue
            method_name = get_member_property_name(nodes, callee)
            # if method_name is None:
            #     continue
            if method_name not in _HIGHER_ORDER_METHODS:
                continue

            args = get_call_arguments(nodes, idx)
            has_callback = any(nodes[a].name in _CALLBACK_NODE_NAMES for a in args)
            if not has_callback:
                continue

            begin = nodes[idx].begin
            end = nodes[idx].end
            snippet = code[begin:end][:200]
            yield PatternMatch(
                mb_id=mb_id,
                side="base",
                pattern_id=self.pattern_id,
                confidence="low",
                node_index=idx,
                begin=begin,
                end=end,
                snippet=snippet,
            )
