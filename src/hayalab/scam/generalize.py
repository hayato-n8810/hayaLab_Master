"""複数の cut 部分木から共通部分木（anti-unifier）を求める単体処理。

Anti-unification は複数の項に共通する最小一般化（least general generalization）を作る
操作で、一致する部分は具象のまま残し、食い違う部分を hole に置き換える。
クラスタの全メンバーに適用すれば「そのクラスタが共有している構造」だけが残り、
偶発的な周辺ノードが自動的に落ちる。

cut ノードは ``origin_index`` と ``parent``（root からの祖先 index パス）を持つが、
``origin_index`` は実装対ごとのローカル番号なので、メンバー間のノード対応は
index ではなく**構造上の位置**（親子関係と兄弟位置）で取る。

hole の種類:
    ``value_hole``: 全メンバーで ``name`` は一致するが ``value`` が異なる。
    ``node_hole`` : ``name`` が食い違う。その位置以下は辿らない。
    ``tail_hole`` : 子の個数が食い違う。共通する先頭までを残し、残りを 1 つに畳む。
"""

from __future__ import annotations

from typing import Any

# hole を表すときの表示用 value
VALUE_HOLE = "$?"
NODE_HOLE_NAME = "?"
TAIL_HOLE_NAME = "..."


def build_forest(nodes: list[dict[str, Any]]) -> tuple[list[int], dict[int, list[int]]]:
    """Cut ノード列から ``(root の origin_index 列, 親 → 子 origin_index 列)`` を作る。

    直接の親が cut に残っていない場合は ``parent`` を末尾から遡り、最も近い残存祖先に
    接ぐ。祖先が 1 つも残っていないノードは root として扱う。子の並びは
    ``origin_index`` 昇順（= 前順走査順）とする。

    Args:
        nodes: cutout の ``nodes`` リスト。

    Returns:
        ``(roots, children)``。``children`` は origin_index をキーに持つ。
    """
    present = {n["origin_index"] for n in nodes}
    roots: list[int] = []
    children: dict[int, list[int]] = {n["origin_index"]: [] for n in nodes}
    for node in sorted(nodes, key=lambda n: n["origin_index"]):
        index = node["origin_index"]
        parent_index = None
        for ancestor in reversed(node.get("parent") or []):
            if ancestor != index and ancestor in present:
                parent_index = ancestor
                break
        if parent_index is None:
            roots.append(index)
        else:
            children[parent_index].append(index)
    return roots, children


def anti_unify(cuts: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """複数の cut に共通する部分木を返す（一致部分は具象、不一致は hole）。

    各 cut の root 列を位置で対応づけ、以降は兄弟位置で再帰的に対応づける。位置による
    対応は同一構文構造を仮定するが、クラスタは同一構造で括られているため妥当な近似で、
    木編集距離のような組合せ探索を必要としない。

    Args:
        cuts: メンバーごとの ``nodes`` リスト。比較は各ノードの ``name`` と ``value``
            で行うため、抽象化レベルを反映した ``value`` を渡すこと。

    Returns:
        ``[{"name", "value", "depth", "kind"}, ...]`` を前順で並べたリスト。
        ``kind`` は ``"concrete"`` / ``"value_hole"`` / ``"node_hole"`` / ``"tail_hole"``。
        ``concrete`` と ``value_hole`` には先頭メンバーの ``label`` を透過して付ける
        （終端ノード判定など、 呼び出し側の書式判断に使う）。 ``cuts`` が空なら空リスト。
    """
    if not cuts:
        return []

    forests = [build_forest(cut) for cut in cuts]
    node_of = [{n["origin_index"]: n for n in cut} for cut in cuts]
    out: list[dict[str, Any]] = []

    def walk(indices: list[int], depth: int) -> None:
        """各メンバーの対応ノード 1 組を一般化して ``out`` へ積む。"""
        nodes = [node_of[i][index] for i, index in enumerate(indices)]
        names = {n["name"] for n in nodes}
        if len(names) > 1:
            out.append({"name": NODE_HOLE_NAME, "value": "", "depth": depth, "kind": "node_hole"})
            return
        values = {n.get("value") or "" for n in nodes}
        label = nodes[0].get("label", "")
        if len(values) == 1:
            out.append(
                {
                    "name": nodes[0]["name"],
                    "value": next(iter(values)),
                    "depth": depth,
                    "kind": "concrete",
                    "label": label,
                }
            )
        else:
            out.append(
                {
                    "name": nodes[0]["name"],
                    "value": VALUE_HOLE,
                    "depth": depth,
                    "kind": "value_hole",
                    "label": label,
                }
            )

        child_lists = [forests[i][1][index] for i, index in enumerate(indices)]
        common = min(len(c) for c in child_lists)
        for position in range(common):
            walk([c[position] for c in child_lists], depth + 1)
        if any(len(c) > common for c in child_lists):
            out.append({"name": TAIL_HOLE_NAME, "value": "", "depth": depth + 1, "kind": "tail_hole"})

    root_lists = [roots for roots, _children in forests]
    common_roots = min(len(r) for r in root_lists)
    for position in range(common_roots):
        walk([r[position] for r in root_lists], 0)
    if any(len(r) > common_roots for r in root_lists):
        out.append({"name": TAIL_HOLE_NAME, "value": "", "depth": 0, "kind": "tail_hole"})
    return out


def subtree_nodes(nodes: list[dict[str, Any]], anchor: int) -> list[dict[str, Any]]:
    """``anchor`` を根とする部分木のノード列を返す。

    Args:
        nodes: cutout の ``nodes`` リスト。
        anchor: 根とする ``origin_index``。

    Returns:
        anchor 自身とその子孫（``parent`` パスに anchor を含むノード）。
    """
    return [n for n in nodes if n["origin_index"] == anchor or anchor in (n.get("parent") or [])]


def anti_unify_anchored(cuts: list[list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], str]:
    """共通ノード名を根の候補として探索し、最大の共通部分木を返す。

    :func:`anti_unify` は各 cut の root を位置で対応づけるため、cut の始まりが揃わない
    クラスタでは先頭で name 不一致となり何も残らない。本関数は全メンバーに共通する
    ノード名をアンカー候補とし、各メンバーでその名前を持つ最大の部分木を選んで
    :func:`anti_unify` を適用する。具象ノードが最も多く残るアンカーを採用する。

    Args:
        cuts: メンバーごとの ``nodes`` リスト（``value`` は抽象化レベル反映済み）。

    Returns:
        ``(一般化結果, 採用したアンカーのノード名)``。共通名が無ければ
        :func:`anti_unify` の結果と空文字列を返す。
    """
    if not cuts:
        return [], ""

    name_sets = [{n["name"] for n in cut} for cut in cuts]
    common_names = set.intersection(*name_sets) if name_sets else set()
    if not common_names:
        return anti_unify(cuts), ""

    best: tuple[int, list[dict[str, Any]], str] | None = None
    for name in sorted(common_names):
        candidate_cuts: list[list[dict[str, Any]]] = []
        for cut in cuts:
            anchors = [n["origin_index"] for n in cut if n["name"] == name]
            subtrees = [subtree_nodes(cut, anchor) for anchor in anchors]
            candidate_cuts.append(max(subtrees, key=len))
        generalized = anti_unify(candidate_cuts)
        score = sum(1 for g in generalized if g["kind"] == "concrete")
        if best is None or score > best[0]:
            best = (score, generalized, name)

    assert best is not None
    return best[1], best[2]
