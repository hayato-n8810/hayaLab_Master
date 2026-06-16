r"""Cut 部分木に matcher 群を適用して既知パターンを構造的に同定する。

字句的な署名述語に代えて、 cut（部分木）に matcher を**検出ロジック無改変**で
適用し、 変更前構造の有無で同定する。

cut 部分木への無改変対応:
    ast_nav は ``nodes[idx].parent``（root からの祖先 full-tree インデックスのパス）と
    「リスト位置 idx」が一致している前提で子を辿る（``walk_pre`` は単なる range(len)）。
    cut ノードは ``origin_index`` と full parent パスを保持しているため、
    「リスト位置 = origin_index のスパース配列」を組めば matcher を無改変で流せる。
    欠損位置は placeholder（name="__absent__", parent=[-1] のセンチネル）で埋める。
    実ノードの親パスは全て >=0 なので placeholder はどの候補名にも一致せず、
    子探索でも拾われない。結果として cut に含まれるノード間だけが正しく辿られ、
    cut の外のノードは「存在しない」ものとして扱われる（cut が捉えた範囲のみで判定）。

注:
    同定は Stage A（変更前構造の検出）のみを用いる。 is_base_covered / Stage B の
    diff 連動フィルタは使わない（字句述語と同じく「代表の before 構造の有無」に対応）。
    matcher は具体ノード（value/name）で判定するため抽象化レベルに依存せず、
    結果は (pair id, depth) のみで決まる。
"""

from __future__ import annotations

from hayalab.classes.gumtree import ASTNode

from .p01_for_in_has_own import ForInHasOwnMatcher
from .p02_substr_single_char import SubstrSingleCharMatcher
from .p03_string_cast import StringCastMatcher
from .p06_split_join_chain import SplitJoinChainMatcher
from .p07_to_string_call import ToStringCallMatcher
from .p08_modulo_even_odd import ModuloEvenOddMatcher
from .p09_higher_order_array import HigherOrderArrayMatcher

# RQ1 で評価する 7 パターンの matcher（検出ロジックは無改変）
MATCHERS = {
    1: ForInHasOwnMatcher(),
    2: SubstrSingleCharMatcher(),
    3: StringCastMatcher(),
    6: SplitJoinChainMatcher(),
    7: ToStringCallMatcher(),
    8: ModuloEvenOddMatcher(),
    9: HigherOrderArrayMatcher(),
}

_NODE_FIELDS = ("begin", "end", "label", "name", "value", "parent")


def build_subtree_nodes(cut_nodes: list[dict]) -> list[ASTNode]:
    """Cut ノード列から、リスト位置 = origin_index のスパース ASTNode 配列を組む。

    欠損位置は placeholder（matcher に拾われないノード）で埋める。

    Args:
        cut_nodes: cutout の ``nodes`` リスト（``origin_index`` と ``parent`` を持つ）。

    Returns:
        ``len = max(origin_index) + 1`` のスパース ASTNode 配列。
    """
    max_idx = 0
    for n in cut_nodes:
        max_idx = max(max_idx, n["origin_index"])
        if n.get("parent"):
            max_idx = max(max_idx, max(n["parent"]))

    placeholder = ASTNode(begin=0, end=0, label="", name="__absent__", value="", parent=[-1])
    arr: list[ASTNode] = [placeholder] * (max_idx + 1)
    for n in cut_nodes:
        arr[n["origin_index"]] = ASTNode(**{k: n[k] for k in _NODE_FIELDS})
    return arr


def match_patterns_on_cut(cut_nodes: list[dict]) -> set[int]:
    """Cut 部分木に各 matcher（Stage A のみ）を流し、検出されたパターン id 集合を返す。

    Args:
        cut_nodes: cutout の ``nodes`` リスト。空なら空集合を返す。

    Returns:
        検出されたパターン id（``MATCHERS`` のキー）の集合。
    """
    if not cut_nodes:
        return set()
    nodes = build_subtree_nodes(cut_nodes)
    hit: set[int] = set()
    for pid, matcher in MATCHERS.items():
        for _pm in matcher.find(nodes, "", mb_id=0):
            hit.add(pid)
            break  # 1 件でも検出されれば充足
    return hit
