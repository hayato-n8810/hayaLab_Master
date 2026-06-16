"""フラット AST 用ナビゲーションヘルパー。

MBDiff.json の base_ast.tree（ASTNode のリスト）に対して動作する純関数群。
I/O・パス決定を含まない。
"""

from collections.abc import Iterator
from typing import Union

from hayalab.classes.gumtree import ASTNode

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

PUNCT: frozenset[str] = frozenset({".", ",", ";", ":", "(", ")", "[", "]", "{", "}", '"', "'", "`"})

OPERATOR_SET: frozenset[str] = frozenset(
    {
        "==",
        "===",
        "!=",
        "!==",
        "<",
        "<=",
        ">",
        ">=",
        "+",
        "-",
        "*",
        "/",
        "%",
        "**",
        "&",
        "|",
        "^",
        "<<",
        ">>",
        ">>>",
        "&&",
        "||",
        "??",
        "in",
        "instanceof",
    }
)

# ---------------------------------------------------------------------------
# 基本ナビゲーション
# ---------------------------------------------------------------------------


def direct_children(nodes: list[ASTNode], idx: int) -> list[int]:
    """node[idx] の直接の子インデックスを source 順で返す（punctuation も含む）。

    Args:
        nodes: ASTNode のリスト。
        idx: 親ノードのインデックス。

    Returns:
        直接の子ノードのインデックスリスト（source 順）。
    """
    parent_path = nodes[idx].parent + [idx]
    return [j for j in range(idx + 1, len(nodes)) if nodes[j].parent == parent_path]


def named_children(nodes: list[ASTNode], idx: int) -> list[int]:
    """direct_children から PUNCT を除いたものを返す。

    Args:
        nodes: ASTNode のリスト。
        idx: 親ノードのインデックス。

    Returns:
        punctuation 以外の直接の子ノードのインデックスリスト。
    """
    return [c for c in direct_children(nodes, idx) if nodes[c].name not in PUNCT]


def find_first_child(nodes: list[ASTNode], idx: int, name: Union[str, set[str]]) -> int | None:
    """direct_children のうち、最初に name に一致するものを返す。

    Args:
        nodes: ASTNode のリスト。
        idx: 親ノードのインデックス。
        name: 検索するノード名（文字列または集合）。

    Returns:
        最初に一致した子のインデックス、なければ None。
    """
    if isinstance(name, str):
        name = {name}
    for c in direct_children(nodes, idx):
        if nodes[c].name in name:
            return c
    return None


# ---------------------------------------------------------------------------
# call_expression ヘルパー
# ---------------------------------------------------------------------------


def get_call_callee(nodes: list[ASTNode], call_idx: int) -> int | None:
    """call_expression の callee（最初の named child）を返す。

    Args:
        nodes: ASTNode のリスト。
        call_idx: call_expression ノードのインデックス。

    Returns:
        callee ノードのインデックス、なければ None。
    """
    nc = named_children(nodes, call_idx)
    return nc[0] if nc else None


def get_call_arguments(nodes: list[ASTNode], call_idx: int) -> list[int]:
    """call_expression > arguments の named children（位置引数のインデックス列）を返す。

    Args:
        nodes: ASTNode のリスト。
        call_idx: call_expression ノードのインデックス。

    Returns:
        arguments ノード内の named children のインデックスリスト。
    """
    args_node = find_first_child(nodes, call_idx, "arguments")
    if args_node is None:
        return []
    return named_children(nodes, args_node)


# ---------------------------------------------------------------------------
# member_expression ヘルパー
# ---------------------------------------------------------------------------


def get_member_object(nodes: list[ASTNode], member_idx: int) -> int | None:
    """member_expression の object（最初の named child）を返す。

    Args:
        nodes: ASTNode のリスト。
        member_idx: member_expression ノードのインデックス。

    Returns:
        object ノードのインデックス、なければ None。
    """
    nc = named_children(nodes, member_idx)
    # named_children では property_identifier も含まれるので最初の要素が object
    return nc[0] if nc else None


def get_member_property_name(nodes: list[ASTNode], member_idx: int) -> str | None:
    """member_expression の property_identifier.value を返す。

    Args:
        nodes: ASTNode のリスト。
        member_idx: member_expression ノードのインデックス。

    Returns:
        property_identifier の value 文字列、なければ None。
    """
    prop = find_first_child(nodes, member_idx, "property_identifier")
    if prop is None:
        return None
    return nodes[prop].value


# ---------------------------------------------------------------------------
# binary_expression ヘルパー
# ---------------------------------------------------------------------------


def get_binary_operator(nodes: list[ASTNode], bin_idx: int) -> str | None:
    """binary_expression の演算子記号を返す。

    direct_children の中で PUNCT に含まれず OPERATOR_SET に含まれる name を持つノードを探す。

    Args:
        nodes: ASTNode のリスト。
        bin_idx: binary_expression ノードのインデックス。

    Returns:
        演算子文字列、なければ None。
    """
    for c in direct_children(nodes, bin_idx):
        n = nodes[c].name
        if n not in PUNCT and n in OPERATOR_SET:
            return n
    return None


def get_binary_lhs(nodes: list[ASTNode], bin_idx: int) -> int | None:
    """binary_expression の左オペランド（最初の named child で operator 以外）を返す。

    Args:
        nodes: ASTNode のリスト。
        bin_idx: binary_expression ノードのインデックス。

    Returns:
        左オペランドのインデックス、なければ None。
    """
    for c in named_children(nodes, bin_idx):
        if nodes[c].name not in OPERATOR_SET:
            return c
    return None


def get_binary_rhs(nodes: list[ASTNode], bin_idx: int) -> int | None:
    """binary_expression の右オペランド（最後の named child で operator 以外）を返す。

    Args:
        nodes: ASTNode のリスト。
        bin_idx: binary_expression ノードのインデックス。

    Returns:
        右オペランドのインデックス、なければ None。
    """
    candidates = [c for c in named_children(nodes, bin_idx) if nodes[c].name not in OPERATOR_SET]
    return candidates[-1] if len(candidates) >= 2 else None


# ---------------------------------------------------------------------------
# if_statement ヘルパー
# ---------------------------------------------------------------------------


def get_if_condition_expr(nodes: list[ASTNode], if_idx: int) -> int | None:
    """if_statement の parenthesized_expression の中身式を返す。

    Args:
        nodes: ASTNode のリスト。
        if_idx: if_statement ノードのインデックス。

    Returns:
        条件式ノードのインデックス、なければ None。
    """
    paren = find_first_child(nodes, if_idx, "parenthesized_expression")
    if paren is None:
        return None
    nc = named_children(nodes, paren)
    return nc[0] if nc else None


def get_if_consequence(nodes: list[ASTNode], if_idx: int) -> int | None:
    """if_statement の本体 statement（statement_block 等）を返す。

    parenthesized_expression の次の named child を consequence とみなす。

    Args:
        nodes: ASTNode のリスト。
        if_idx: if_statement ノードのインデックス。

    Returns:
        consequence ノードのインデックス、なければ None。
    """
    nc = named_children(nodes, if_idx)
    # named_children: [if_kw?, parenthesized_expression, consequence, (else_clause)?]
    # "if" キーワードは named_children に含まれる（name=="if"）が punctuation ではない
    # parenthesized_expression の後のものが consequence
    found_paren = False
    for c in nc:
        if nodes[c].name == "parenthesized_expression":
            found_paren = True
            continue
        if found_paren:
            return c
    return None


# ---------------------------------------------------------------------------
# for_in_statement ヘルパー
# ---------------------------------------------------------------------------


def get_for_in_body(nodes: list[ASTNode], for_in_idx: int) -> int | None:
    """for_in_statement の body statement（最後の named child）を返す。

    Args:
        nodes: ASTNode のリスト。
        for_in_idx: for_in_statement ノードのインデックス。

    Returns:
        body statement ノードのインデックス、なければ None。
    """
    nc = named_children(nodes, for_in_idx)
    return nc[-1] if nc else None


# ---------------------------------------------------------------------------
# statement_block ヘルパー
# ---------------------------------------------------------------------------


def first_named_statement(nodes: list[ASTNode], block_idx: int) -> int | None:
    """statement_block の最初の named child（最初の文）を返す。

    Args:
        nodes: ASTNode のリスト。
        block_idx: statement_block ノードのインデックス。

    Returns:
        最初の named child のインデックス、なければ None。
    """
    nc = named_children(nodes, block_idx)
    return nc[0] if nc else None


# ---------------------------------------------------------------------------
# リテラル判定ヘルパー
# ---------------------------------------------------------------------------


def is_empty_string_literal(nodes: list[ASTNode], str_idx: int) -> bool:
    """String ノードに string_fragment / escape_sequence / html_character_reference を 1 つも含まないか確認する。

    Args:
        nodes: ASTNode のリスト。
        str_idx: string ノードのインデックス。

    Returns:
        空文字列リテラルであれば True。
    """
    content_types = {"string_fragment", "escape_sequence", "html_character_reference"}
    for c in direct_children(nodes, str_idx):
        if nodes[c].name in content_types:
            return False
    return True


def is_number_literal(nodes: list[ASTNode], idx: int, value: Union[str, set[str]]) -> bool:
    """Name == 'number' かつ value が一致するか確認する。

    Args:
        nodes: ASTNode のリスト。
        idx: チェック対象ノードのインデックス。
        value: 期待する値（文字列または集合）。

    Returns:
        条件を満たせば True。
    """
    if isinstance(value, str):
        value = {value}
    return nodes[idx].name == "number" and nodes[idx].value in value


def is_identifier(nodes: list[ASTNode], idx: int, value: str | None = None) -> bool:
    """Name == 'identifier' （value 指定時はそれにも一致）か確認する。

    Args:
        nodes: ASTNode のリスト。
        idx: チェック対象ノードのインデックス。
        value: 期待する value（省略可）。

    Returns:
        条件を満たせば True。
    """
    if nodes[idx].name != "identifier":
        return False
    if value is not None:
        return nodes[idx].value == value
    return True


def is_property_identifier(nodes: list[ASTNode], idx: int, value: str | None = None) -> bool:
    """Name == 'property_identifier' （value 指定時はそれにも一致）か確認する。

    Args:
        nodes: ASTNode のリスト。
        idx: チェック対象ノードのインデックス。
        value: 期待する value（省略可）。

    Returns:
        条件を満たせば True。
    """
    if nodes[idx].name != "property_identifier":
        return False
    if value is not None:
        return nodes[idx].value == value
    return True


# ---------------------------------------------------------------------------
# トラバーサル
# ---------------------------------------------------------------------------


def walk_pre(nodes: list[ASTNode]) -> Iterator[int]:
    """0..len(nodes) を順に返す（ソース pre-order に等しい）。

    Args:
        nodes: ASTNode のリスト。

    Yields:
        インデックス 0 から len(nodes)-1 まで。
    """
    for i in range(len(nodes)):
        yield i


# ---------------------------------------------------------------------------
# Phase 3 補助: binary_expression の両辺条件マッチ
# ---------------------------------------------------------------------------


def match_either(
    nodes: list[ASTNode],
    bin_idx: int,
    pred_a,
    pred_b,
) -> tuple[int, int] | None:
    """binary_expression の lhs/rhs について、一方が pred_a を、もう一方が pred_b を満たすペアを返す。

    両方向（lhs=A, rhs=B）と（lhs=B, rhs=A）を試行する。

    Args:
        nodes: ASTNode のリスト。
        bin_idx: binary_expression ノードのインデックス。
        pred_a: 条件 A の述語 (nodes, idx) -> bool。
        pred_b: 条件 B の述語 (nodes, idx) -> bool。

    Returns:
        (a_idx, b_idx) のタプル、どちらも満たせば返す。一致しなければ None。
    """
    lhs = get_binary_lhs(nodes, bin_idx)
    rhs = get_binary_rhs(nodes, bin_idx)
    if lhs is None or rhs is None:
        return None
    if pred_a(nodes, lhs) and pred_b(nodes, rhs):
        return (lhs, rhs)
    if pred_a(nodes, rhs) and pred_b(nodes, lhs):
        return (rhs, lhs)
    return None
