"""Stage B: diff 連動フィルタ。

PatternMatch に対して base_actions / head_actions / head_nodes を参照し、
起点ノードが実際に fast 版で書き換えられているかを判定する。

判定ルール:
  base_covered（以下のいずれか）
    B1: base_actions の tree.index または ancestors.index が node_index に一致
    B2: base_actions のいずれかの tree.index が起点ノードの **AST subtree** に含まれる
        （= action.index の parent path 上に node_index が存在する）

  head_covered:
    head_actions の subtree（action.index を起点とする部分木）配下に、論文の after に対応する
    head 側ノードが存在する。anchor として ancestors は最近接 1 段のみ使用し、`program` 等の
    最上位を含めない（含めると変更と無関係な既存ノードが anchor 配下に入ってしまうため）。

最終判定: diff_linked = base_covered AND head_covered

修正履歴:
  - B2 のバイト範囲比較バグを修正：action.index は **ノードインデックス** であり、
    起点ノードの byte 範囲 [begin, end) と直接比較するのは型エラー。subtree 包含で再定義。
  - head anchor の ancestors を最近接 1 段に制限：以前は ancestors を全て anchor に加えて
    いたが、program など最上位を含めるため、既存（未変更）ノードまで anchor の subtree と
    みなされ AFTER パターン候補が膨らんでいた。
"""

from __future__ import annotations

from dataclasses import replace

from hayalab.classes.gumtree import ASTNode, GumAction

from .ast_nav import (
    get_binary_rhs,
    get_call_callee,
    get_member_object,
    get_member_property_name,
    is_identifier,
    is_number_literal,
    named_children,
)
from .slow_patterns.base import PatternMatch

# ---------------------------------------------------------------------------
# 定数: pattern_id → head 側に期待される after ノードの name
# ---------------------------------------------------------------------------

_AFTER_KIND: dict[int, str | set[str]] = {
    1: "call_expression",  # Object.keys(...) の呼び出し（for ヘッダ内/外を問わない）
    2: {"subscript_expression"},  # str[i]
    3: "binary_expression",  # x + (string_literal | VAR_*)
    4: "call_expression",  # .empty()
    5: "call_expression",  # .charAt()
    6: "call_expression",  # .replace()
    7: {"binary_expression", "call_expression"},  # instanceof / typeof / Array.isArray
    8: "binary_expression",  # & 1
    9: "for_statement",
    10: {"if_statement", "ternary_expression"},  # if 文 + ===/!== もしくは三項演算子 + ===/!==
}


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


def _binary_has_operator(nodes: list[ASTNode], bin_idx: int, op: str) -> bool:
    """binary_expression が指定の演算子を持つか確認する。

    Args:
        nodes: ASTNode のリスト。
        bin_idx: binary_expression ノードのインデックス。
        op: 期待する演算子の name。

    Returns:
        条件を満たせば True。
    """
    parent_path = nodes[bin_idx].parent + [bin_idx]
    for j in range(bin_idx + 1, len(nodes)):
        if nodes[j].parent == parent_path and nodes[j].name == op:
            return True
    return False


def _has_member_property(nodes: list[ASTNode], call_idx: int, prop_name: str) -> bool:
    """call_expression の callee が member_expression で指定 property を持つか確認する。

    Args:
        nodes: ASTNode のリスト。
        call_idx: call_expression ノードのインデックス。
        prop_name: 期待する property_identifier の value。

    Returns:
        条件を満たせば True。
    """
    parent_path = nodes[call_idx].parent + [call_idx]
    for j in range(call_idx + 1, len(nodes)):
        if nodes[j].parent != parent_path:
            continue
        if nodes[j].name != "member_expression":
            continue
        member_parent_path = nodes[j].parent + [j]
        for k in range(j + 1, len(nodes)):
            if nodes[k].parent == member_parent_path and nodes[k].name == "property_identifier":
                if nodes[k].value == prop_name:
                    return True
        break
    return False


def _is_object_keys_call(head_nodes: list[ASTNode], call_idx: int) -> bool:
    """call_expression が Object.keys(...) かを判定する。

    Args:
        head_nodes: head 側 ASTNode リスト。
        call_idx: call_expression のインデックス。

    Returns:
        Object.keys(...) なら True。
    """
    callee = get_call_callee(head_nodes, call_idx)
    if callee is None or head_nodes[callee].name != "member_expression":
        return False
    if get_member_property_name(head_nodes, callee) != "keys":
        return False
    obj = get_member_object(head_nodes, callee)
    if obj is None:
        return False
    return is_identifier(head_nodes, obj, "Object")


def _get_call_receiver_identifier(nodes: list[ASTNode], call_idx: int) -> str | None:
    """call_expression の receiver（member_expression.object）が identifier ならその value を返す。

    `obj.method(...)` の `obj` 部分が単純な identifier の場合のみ value を返す。
    `$(this).method(...)` 等の複雑な式の場合は None を返す。

    Args:
        nodes: ASTNode のリスト。
        call_idx: call_expression ノードのインデックス。

    Returns:
        identifier の value、識別できなければ None。
    """
    callee = get_call_callee(nodes, call_idx)
    if callee is None or nodes[callee].name != "member_expression":
        return None
    obj = get_member_object(nodes, callee)
    if obj is None:
        return None
    if nodes[obj].name != "identifier":
        return None
    return nodes[obj].value


def _binary_with_typeof_eq(head_nodes: list[ASTNode], bin_idx: int) -> bool:
    """binary_expression が typeof X === "..." / typeof X !== "..." 形式かを判定する。

    `typeof X` は tree-sitter-javascript では unary_expression（演算子 typeof）として
    表現される。これと文字列リテラルの === / !== 比較なら True を返す。

    Args:
        head_nodes: head 側 ASTNode リスト。
        bin_idx: binary_expression のインデックス。

    Returns:
        条件を満たせば True。
    """
    if not (_binary_has_operator(head_nodes, bin_idx, "===") or _binary_has_operator(head_nodes, bin_idx, "!==")):
        return False
    parent_path = head_nodes[bin_idx].parent + [bin_idx]
    has_typeof = False
    has_string = False
    for j in range(bin_idx + 1, len(head_nodes)):
        if head_nodes[j].parent != parent_path:
            continue
        node = head_nodes[j]
        if node.name == "unary_expression":
            # unary_expression の演算子 typeof を探す
            unary_parent = node.parent + [j]
            for k in range(j + 1, len(head_nodes)):
                if head_nodes[k].parent == unary_parent and head_nodes[k].name == "typeof":
                    has_typeof = True
                    break
        elif node.name == "string":
            has_string = True
    return has_typeof and has_string


def _is_empty_string_node(head_nodes: list[ASTNode], idx: int) -> bool:
    """ノードが空文字列リテラル `""` / `''` かを判定する。

    tree-sitter-javascript では文字列リテラルは `string` ノードで、内容があれば
    `string_fragment` 子ノードを持つ。空文字列は string_fragment を持たない
    （または string_fragment.value が空文字列）。

    Args:
        head_nodes: head 側 ASTNode リスト。
        idx: チェック対象ノードのインデックス。

    Returns:
        空文字列リテラルなら True。
    """
    if head_nodes[idx].name != "string":
        return False
    parent_path = head_nodes[idx].parent + [idx]
    for j in range(idx + 1, len(head_nodes)):
        if head_nodes[j].parent != parent_path:
            continue
        if head_nodes[j].name == "string_fragment":
            return head_nodes[j].value == ""
        # 子要素を一通り見たら break（pre-order なので parent が深くなったら別の sibling）
        if len(head_nodes[j].parent) < len(parent_path):
            break
    # string_fragment 子がなければ空文字列
    return True


def _binary_plus_with_empty_string(head_nodes: list[ASTNode], bin_idx: int) -> bool:
    """binary_expression が `+` で、直 child の **少なくとも一方が空文字列** か判定する。

    ID3 (String(x) → "" + x / x + "") の AFTER 判定用。target.md の例にあるように
    片方のオペランドは empty string でなければならない。「任意の文字列 + 変数」を
    許容すると関数本体が全リファクタされた場合の `Array(...).join(",") + VAR` 等が
    全て該当してしまうため、空文字列に限定する。

    Args:
        head_nodes: head 側 ASTNode リスト。
        bin_idx: binary_expression のインデックス。

    Returns:
        条件を満たせば True。
    """
    if not _binary_has_operator(head_nodes, bin_idx, "+"):
        return False
    parent_path = head_nodes[bin_idx].parent + [bin_idx]
    for j in range(bin_idx + 1, len(head_nodes)):
        if head_nodes[j].parent != parent_path:
            continue
        if head_nodes[j].name == "string" and _is_empty_string_node(head_nodes, j):
            return True
    return False


def _if_has_eq_neq_in_condition(head_nodes: list[ASTNode], if_idx: int) -> bool:
    """if_statement の condition 配下に === / !== の binary_expression があるか判定する。

    Args:
        head_nodes: head 側 ASTNode リスト。
        if_idx: if_statement のインデックス。

    Returns:
        条件を満たせば True。
    """
    if_parent_path = head_nodes[if_idx].parent + [if_idx]
    for j in range(if_idx + 1, len(head_nodes)):
        node = head_nodes[j]
        # if_statement の子孫に限定
        if len(node.parent) < len(if_parent_path):
            break  # pre-order なので親パスより浅くなったら抜ける
        if node.parent[: len(if_parent_path)] != if_parent_path:
            break
        if node.name == "binary_expression":
            if _binary_has_operator(head_nodes, j, "===") or _binary_has_operator(head_nodes, j, "!=="):
                return True
    return False


def _ternary_has_eq_neq_in_condition(head_nodes: list[ASTNode], ternary_idx: int) -> bool:
    """ternary_expression の condition が === / !== の binary_expression か判定する。

    `cond ? x : y` の cond 部分（最初の named child）を取り出し、binary_expression で
    === または !== の演算子を持つかを確認する。

    Args:
        head_nodes: head 側 ASTNode リスト。
        ternary_idx: ternary_expression のインデックス。

    Returns:
        condition が === / !== の binary_expression なら True。
    """
    children = named_children(head_nodes, ternary_idx)
    if not children:
        return False
    cond_idx = children[0]
    if head_nodes[cond_idx].name != "binary_expression":
        return False
    return _binary_has_operator(head_nodes, cond_idx, "===") or _binary_has_operator(head_nodes, cond_idx, "!==")


def _head_matches_after_for_pattern(
    pattern_id: int,
    head_node: ASTNode,
    head_nodes: list[ASTNode],
    head_idx: int,
    base_nodes: list[ASTNode] | None = None,
    base_node_index: int | None = None,
) -> bool:
    """Head 側ノードが論文の after パターンに対応するかを判定する。

    Args:
        pattern_id: パターン番号（1〜10）。
        head_node: head 側の候補ノード。
        head_nodes: head 側の全 ASTNode リスト。
        head_idx: head 側の候補ノードインデックス。
        base_nodes: base 側 ASTNode リスト（任意、ID4 の receiver 比較で使用）。
        base_node_index: base 側起点ノード（PatternMatch.node_index）。

    Returns:
        after パターンに対応すれば True。
    """
    expected = _AFTER_KIND.get(pattern_id)
    if expected is None:
        return False

    expected_set = {expected} if isinstance(expected, str) else expected
    if head_node.name not in expected_set:
        return False

    if pattern_id == 1:
        # head_node は call_expression。Object.keys(...) か確認する。
        return _is_object_keys_call(head_nodes, head_idx)

    if pattern_id == 2:
        # subscript_expression の `[` トークン直前にある最初の直接子（object 相当）が
        # identifier / member_expression / call_expression なら True。
        # tree-sitter-javascript では field 名 "object" は別ノードにならず、object 相当
        # ノードが subscript_expression の最初の named 子として直接現れる。
        parent_path = head_nodes[head_idx].parent + [head_idx]
        object_kinds = {"identifier", "member_expression", "call_expression"}
        for j in range(head_idx + 1, len(head_nodes)):
            if head_nodes[j].parent != parent_path:
                continue
            if head_nodes[j].name == "[":
                break
            if head_nodes[j].name in object_kinds:
                return True
        return False

    if pattern_id == 3:
        # `"" + x` または `x + ""` 形に限定（target.md ID3 の after 例どおり）
        return _binary_plus_with_empty_string(head_nodes, head_idx)

    if pattern_id == 4:
        if not _has_member_property(head_nodes, head_idx, "empty"):
            return False
        # receiver 同一性チェック（base_nodes 未指定 / 識別不能なら緩く True を返す）
        if base_nodes is None or base_node_index is None:
            return True
        base_recv = _get_call_receiver_identifier(base_nodes, base_node_index)
        head_recv = _get_call_receiver_identifier(head_nodes, head_idx)
        if base_recv is None or head_recv is None:
            return True
        return base_recv == head_recv

    if pattern_id == 5:
        return _has_member_property(head_nodes, head_idx, "charAt")

    if pattern_id == 6:
        return _has_member_property(head_nodes, head_idx, "replace")

    if pattern_id == 7:
        # target.md ID7 は instanceof への置換が主旨。typeof X === "..." 形式は
        # ID7 とは別カテゴリの最適化（typeof 比較）であり、論文の意図と異なる。
        # binary_expression: instanceof のみ許容
        if head_node.name == "binary_expression":
            return _binary_has_operator(head_nodes, head_idx, "instanceof")
        # call_expression: Array.isArray(...) は instanceof Array と意味的に同等の組込み判定。
        # 既存の TRUE 事例（toString.call(arr) === "[object Array]" → Array.isArray(arr)）の
        # 互換性のため許容を残す。
        if head_node.name == "call_expression":
            return _has_member_property(head_nodes, head_idx, "isArray")
        return False

    if pattern_id == 8:
        # & 1 を要求（rhs が number:1）
        if not _binary_has_operator(head_nodes, head_idx, "&"):
            return False
        rhs = get_binary_rhs(head_nodes, head_idx)
        if rhs is None:
            return False
        return is_number_literal(head_nodes, rhs, "1")

    if pattern_id == 9:
        # 9 は for_statement のみ要求。追加条件は今のところ無し。
        return True

    if pattern_id == 10:
        # if_statement: condition 配下に === / !==
        # ternary_expression: condition が === / !==
        if head_node.name == "if_statement":
            return _if_has_eq_neq_in_condition(head_nodes, head_idx)
        if head_node.name == "ternary_expression":
            return _ternary_has_eq_neq_in_condition(head_nodes, head_idx)
        return False

    return True


def _resolve_action_node_index(action: GumAction) -> int | None:
    """GumAction が指す head ノードのインデックスを解決する。

    Args:
        action: GumAction（head_actions の要素）。

    Returns:
        ノードインデックス。解決できなければ None。
    """
    if action.index is not None:
        return action.index
    if action.ancestors:
        # ancestors の最初の要素を起点とみなす（祖先で代替）
        return action.ancestors[0].index
    return None


def _is_descendant_or_self(nodes: list[ASTNode], anchor_idx: int, target_idx: int) -> bool:
    """target_idx が anchor_idx の subtree（自身を含む）に属するか判定する。

    parent パスは「ルートからの親インデックス列」。anchor_idx が target_idx の祖先か
    自身であれば True。base / head どちらの ASTNode リストでも使える共通ヘルパー。

    Args:
        nodes: ASTNode リスト。
        anchor_idx: 起点ノードインデックス。
        target_idx: 判定対象ノードインデックス。

    Returns:
        target_idx が anchor_idx の subtree 内なら True。
    """
    if anchor_idx == target_idx:
        return True
    if anchor_idx < 0 or anchor_idx >= len(nodes):
        return False
    if target_idx < 0 or target_idx >= len(nodes):
        return False
    return anchor_idx in nodes[target_idx].parent


# anchor として除外する最上位ノード深さ。
# parent path の長さがこの値未満のノード（= program ルート）は anchor に含めない。
# program を anchor にすると配下の全 head_nodes が「anchor の subtree」と判定され、
# 変更と無関係な既存ノードまで AFTER 候補に入ってしまう。program-direct-child は
# 局所性が十分なので anchor として許容する。
_MIN_ANCHOR_DEPTH = 1


def _is_useful_anchor(nodes: list[ASTNode], idx: int) -> bool:
    """Anchor として使える程度に局所的なノードか（program 等の最上位ではないか）判定する。

    Args:
        nodes: ASTNode リスト。
        idx: ノードインデックス。

    Returns:
        anchor として有効なら True（parent パス長 >= _MIN_ANCHOR_DEPTH）。
    """
    if idx < 0 or idx >= len(nodes):
        return False
    return len(nodes[idx].parent) >= _MIN_ANCHOR_DEPTH


def _collect_action_anchors(actions: list[GumAction], nodes: list[ASTNode]) -> set[int]:
    """head_actions から AFTER パターン検索の anchor 集合を構築する。

    各 action.index と全 ancestors を候補とし、その中で **program / program 直下の文
    レベルより深いもの** のみ採用する。これにより、

      - GumTree が `.replace(.., ..)` 等を fine-grained に分割して insert した場合でも
        call_expression / member_expression レベルの ancestor が anchor として残り、
        AFTER パターン (call_expression) を正しく拾える（ID6 の TRUE 維持）。
      - program や program 直下の文を anchor にしないことで、変更と無関係な既存ノード
        （別の for ループ等）が「anchor の subtree」に紛れ込むのを防ぐ
        （ID1 の 15415、ID9 の 911/1335 等の false 抑制）。

    Args:
        actions: GumAction のリスト（head_actions）。
        nodes: ASTNode のリスト（head_nodes）。

    Returns:
        anchor として用いるノードインデックス集合。
    """
    anchors: set[int] = set()
    for action in actions:
        if action.index is not None and _is_useful_anchor(nodes, action.index):
            anchors.add(action.index)
        if action.ancestors:
            for anc in action.ancestors:
                if _is_useful_anchor(nodes, anc.index):
                    anchors.add(anc.index)
    return anchors


def _insert_action_anchors(actions: list[GumAction], nodes: list[ASTNode]) -> set[int]:
    """head_actions のうち `insert-*` 系の action に限定して anchor 集合を返す。

    `_collect_action_anchors` の insert-only 版。ID9 のような「新規に挿入された
    AFTER 構造」を要求するパターンで、既存（未変更）ノードを除外するために使う。

    重要: ancestors は **使わない**。ancestors は挿入が行われた位置（既存のコンテキスト）
    を指し、program など最上位を含むため、ancestors を anchor にすると既存の兄弟コード
    （例: program 直下に元から存在する for ループ）まで「挿入された subtree 配下」と
    みなされてしまう。挿入された **本体** のみを anchor とするため action.index のみを使う。

    Args:
        actions: GumAction のリスト（head_actions）。
        nodes: ASTNode のリスト（head_nodes）。

    Returns:
        insert 系 action の anchor として用いるノードインデックス集合（action.index のみ）。
    """
    anchors: set[int] = set()
    for action in actions:
        if not action.action.startswith("insert"):
            continue
        if action.index is not None and 0 <= action.index < len(nodes):
            anchors.add(action.index)
    return anchors


def _has_inserted_node_of_kind(actions: list[GumAction], nodes: list[ASTNode], kind: str) -> bool:
    """`insert-*` action の subtree 配下に指定型名のノードが含まれるか。

    例: kind="for_statement" は、新規に挿入された function_declaration の中に
    for_statement が含まれるケース（id 994/1086 等）も拾える。単に action.tree が
    "for_statement..." で始まる action を探すだけだと、挿入された関数の中の for を
    取り逃すため subtree 走査が必要。

    Args:
        actions: head_actions。
        nodes: head_nodes。
        kind: 期待するノード型名。

    Returns:
        挿入された subtree 配下にそのノード型が存在すれば True。
    """
    insert_anchors = _insert_action_anchors(actions, nodes)
    if not insert_anchors:
        return False
    for h_idx, node in enumerate(nodes):
        if node.name != kind:
            continue
        for anchor in insert_anchors:
            if _is_descendant_or_self(nodes, anchor, h_idx):
                return True
    return False


# ---------------------------------------------------------------------------
# Stage A フィルタ: base_covered 判定
# ---------------------------------------------------------------------------


def is_base_covered(
    pm: PatternMatch,
    base_actions: list[GumAction],
    base_nodes: list[ASTNode] | None = None,
) -> bool:
    """PatternMatch が base_actions の subtree に含まれるかを判定する。

    B1: base_actions のいずれかの action.index == node_index、または
        action.ancestors のいずれかが node_index に一致する。
    B2: base_actions のいずれかの action.index が node_index の **AST subtree** に含まれる
        （= action.index の parent path 上に node_index が現れる）。

    旧 B2 はバイト位置とノードインデックスを比較するバグがあり、無関係な action が
    たまたまノードインデックスがバイト範囲に収まることで base_covered=True になる
    ケースが頻発していた。base_nodes を渡せば AST 包含で正しく判定する。
    base_nodes が None の場合は B2 をスキップ（B1 のみで判定）。

    Args:
        pm: Stage A で生成された PatternMatch。
        base_actions: GumDiff.base_actions（GumAction のリスト）。
        base_nodes: GumDiff.base_ast.tree（ASTNode のリスト）。B2 の subtree 判定に使用。

    Returns:
        base_covered が True なら True。
    """
    node_index = pm.node_index

    # B1
    for action in base_actions:
        if action.index == node_index:
            return True
        if action.ancestors and any(anc.index == node_index for anc in action.ancestors):
            return True

    # B2: action.index が node_index の subtree 内（= node_index が action.index の祖先）
    if base_nodes is not None:
        for action in base_actions:
            if action.index is None:
                continue
            if _is_descendant_or_self(base_nodes, node_index, action.index):
                return True

    return False


# ---------------------------------------------------------------------------
# Stage B エントリポイント
# ---------------------------------------------------------------------------


def apply_diff_link(
    match: PatternMatch,
    base_actions: list[GumAction],
    head_actions: list[GumAction],
    matches: list[tuple[int, int]],
    head_nodes: list[ASTNode],
    base_nodes: list[ASTNode] | None = None,
) -> PatternMatch:
    """PatternMatch に diff_linked / diff_reason を付与して返す。

    判定:
      base_covered = B1 OR B2（base_actions ベース）
      head_covered = head_actions の subtree 内に after パターン候補が存在する
      diff_linked  = base_covered AND head_covered

    Args:
        match: Stage A で生成された PatternMatch。
        base_actions: GumDiff.base_actions（GumAction のリスト）。
        head_actions: GumDiff.head_actions（GumAction のリスト）。
        matches: GumDiff.matches（API 互換のため受け取るが内部判定では未使用）。
        head_nodes: GumDiff.head_ast.tree（ASTNode のリスト）。
        base_nodes: GumDiff.base_ast.tree（ASTNode のリスト）。
            ID4 の receiver 同一性チェック等、base 側との照合が必要なパターンで使用する。

    Returns:
        diff_linked / diff_reason が更新された PatternMatch（frozen dataclass なので新規作成）。
    """
    del matches  # 方針 B では未使用（API 互換のため引数は残す）

    node_index = match.node_index

    # ---- base 側 ----
    b1_met = False
    b2_met = False

    for action in base_actions:
        if action.index == node_index:
            b1_met = True
            break
        if action.ancestors and any(anc.index == node_index for anc in action.ancestors):
            b1_met = True
            break

    # B2: action.index が node_index の subtree に含まれる（AST 包含で判定）
    if base_nodes is not None:
        for action in base_actions:
            if action.index is None:
                continue
            if _is_descendant_or_self(base_nodes, node_index, action.index):
                b2_met = True
                break

    base_covered = b1_met or b2_met

    # ---- head 側 ----
    head_covered = False

    if base_covered and head_actions and head_nodes:
        # head_actions の anchor を構築（action.index + 最近接 ancestors のみ）。
        # ancestors を全段含めると program まで anchor となり、変更と無関係な既存
        # ノードまで AFTER パターン候補に含まれてしまう。
        action_roots = _collect_action_anchors(head_actions, head_nodes)

        # ID9 (reduce → for): 「単に for_statement が head 内に存在する」だけでは
        # 既存の for ループに引っかかるため、新規挿入の subtree 配下に for_statement が
        # あることを要求する（挿入された function_declaration 内部の for も拾うため subtree 走査）。
        if match.pattern_id == 9:
            if not _has_inserted_node_of_kind(head_actions, head_nodes, "for_statement"):
                return match  # head_covered=False のまま

        if action_roots:
            # 各 head ノードを走査し、いずれかの action subtree に属し、
            # かつ after パターンを満たすなら head_covered = True
            for h_idx in range(len(head_nodes)):
                if not any(_is_descendant_or_self(head_nodes, root, h_idx) for root in action_roots):
                    continue
                if _head_matches_after_for_pattern(
                    match.pattern_id,
                    head_nodes[h_idx],
                    head_nodes,
                    h_idx,
                    base_nodes=base_nodes,
                    base_node_index=node_index,
                ):
                    head_covered = True
                    break

    if not (base_covered and head_covered):
        return match

    base_label = "B1" if b1_met else "B2"
    diff_reason = f"base_{base_label}_head_action"

    return replace(match, diff_linked=True, diff_reason=diff_reason)
