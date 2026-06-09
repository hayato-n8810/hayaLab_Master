"""Pattern 1: for-in + hasOwnProperty の検出。

仕様:
  - for_in_statement の body が statement_block または直接 if_statement
  - その（最初の）if_statement の条件が call_expression
  - その call の callee が member_expression で property == "hasOwnProperty"

信頼度:
  - high: member_expression.object の識別子が for-in の右辺（iterated object）と一致
  - medium: 上記が確認できない場合
"""

from __future__ import annotations

from collections.abc import Iterator

from hayalab.classes.gumtree import ASTNode

from ..ast_nav import (
    find_first_child,
    first_named_statement,
    get_call_callee,
    get_for_in_body,
    get_if_condition_expr,
    get_member_object,
    get_member_property_name,
    is_identifier,
    named_children,
    walk_pre,
)
from .base import PatternMatch


def _get_for_in_right(nodes: list[ASTNode], for_in_idx: int) -> int | None:
    """for_in_statement の右辺（被走査オブジェクト）のインデックスを返す。

    右辺は named_children の中で 'in'/'of' キーワードの直後に来る。

    Args:
        nodes: ASTNode のリスト。
        for_in_idx: for_in_statement ノードのインデックス。

    Returns:
        右辺ノードのインデックス、なければ None。
    """
    nc = named_children(nodes, for_in_idx)
    # named_children は: [for_kw, var_kw?, identifier(left), in_kw, identifier(right), body]
    # 'in' または 'of' の次がright
    for i, c in enumerate(nc):
        if nodes[c].name in {"in", "of"}:
            if i + 1 < len(nc):
                return nc[i + 1]
    return None


class ForInHasOwnMatcher:
    """Pattern 1: for-in + hasOwnProperty を検出する matcher。"""

    pattern_id: int = 1
    pattern_name: str = "for_in_has_own"

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から Pattern 1 を検出する。

        Args:
            nodes: base_ast.tree の ASTNode リスト。
            code: base_ast.code の文字列。
            mb_id: MBDiff レコードの id。

        Yields:
            PatternMatch（high または medium confidence）。
        """
        for idx in walk_pre(nodes):
            if nodes[idx].name != "for_in_statement":
                continue

            body_idx = get_for_in_body(nodes, idx)
            if body_idx is None:
                continue

            # body が statement_block の場合は最初の named statement が if
            # body が直接 if_statement の場合も許容（ブレース省略）
            if nodes[body_idx].name == "statement_block":
                if_idx = first_named_statement(nodes, body_idx)
            elif nodes[body_idx].name == "if_statement":
                if_idx = body_idx
            else:
                continue

            if if_idx is None or nodes[if_idx].name != "if_statement":
                continue

            cond_expr = get_if_condition_expr(nodes, if_idx)
            if cond_expr is None:
                continue
            if nodes[cond_expr].name != "call_expression":
                continue

            callee = get_call_callee(nodes, cond_expr)
            if callee is None or nodes[callee].name != "member_expression":
                continue
            if get_member_property_name(nodes, callee) != "hasOwnProperty":
                continue

            # 信頼度判定: object 識別子が for-in の右辺と一致するか
            confidence = "medium"
            member_obj = get_member_object(nodes, callee)
            if member_obj is not None and is_identifier(nodes, member_obj):
                right_idx = _get_for_in_right(nodes, idx)
                if right_idx is not None and is_identifier(nodes, right_idx):
                    if nodes[member_obj].value == nodes[right_idx].value:
                        confidence = "high"

            begin = nodes[idx].begin
            end = nodes[idx].end
            snippet = code[begin:end][:200]
            yield PatternMatch(
                mb_id=mb_id,
                side="base",
                pattern_id=self.pattern_id,
                confidence=confidence,
                node_index=idx,
                begin=begin,
                end=end,
                snippet=snippet,
            )


def _find_if_from_block_or_direct(nodes: list[ASTNode], body_idx: int) -> int | None:
    """statement_block から最初の if_statement を探す（内部ヘルパー）。

    Args:
        nodes: ASTNode のリスト。
        body_idx: body ノードのインデックス。

    Returns:
        if_statement のインデックス、なければ None。
    """
    if nodes[body_idx].name == "statement_block":
        stmt = first_named_statement(nodes, body_idx)
        if stmt is not None and nodes[stmt].name == "if_statement":
            return stmt
    elif nodes[body_idx].name == "if_statement":
        return body_idx
    return None


def _find_call_in_if(nodes: list[ASTNode], if_idx: int) -> int | None:
    """if_statement の条件から call_expression を取得する（内部ヘルパー）。

    Args:
        nodes: ASTNode のリスト。
        if_idx: if_statement ノードのインデックス。

    Returns:
        call_expression のインデックス、なければ None。
    """
    paren = find_first_child(nodes, if_idx, "parenthesized_expression")
    if paren is None:
        return None
    nc = named_children(nodes, paren)
    if not nc:
        return None
    cond = nc[0]
    return cond if nodes[cond].name == "call_expression" else None
