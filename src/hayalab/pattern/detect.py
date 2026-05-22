"""パターン抽出パイプライン Stage 3: 検出器（AST 部分木マッチング）。

単一パターン × 単一 AST の判定 (`detect`) と、単一パターン × データセットの検出結果計算
(`compute_detection`) を提供する。複数パターンの一括計算は呼び出し側 (experiments) で
並列化・多重化することを前提とし、本モジュールは単一処理のみを公開する。

抽象化レベルの 2 軸:
    - 軸1 (literal_generalize) = abst_level >> 1
        識別子マッチ規則: True → プレフィクスのみ一致 (PREFIX_* で任意 PREFIX_n を許容)
                          False → original_value 完全一致
    - 軸2 (gap_tolerant) = abst_level & 1
        子マッチ規則: True → 子列の順序保存部分列埋め込み（追加のみ許容）
                      False → 厳密な zip 一致

検出方式:
    - 正規表現プリフィルタは廃止（抽象化されたノード型を字面で扱えないため）。
    - 「ノード型集合プリフィルタ」(prefilter=True 既定) を採用し、パターンが要求する
      ノード型集合が target AST に存在しなければ即 False を返す。
    - 同一識別子の整合性は AST マッチング側の `theta` (slot_id → 実値バインド) で
      意味的に判定する。
    - prefilter=False を指定すると、上記スクリーニングを行わず全 target ノードに
      対して部分木マッチングを走査する（フルマッチ）。

公開 API:
    - detect(pattern, target_ast, prefilter=True) -> bool
    - compute_detection(pattern, dataset, prefilter=True) -> set[int]
"""

from __future__ import annotations

from typing import Iterable

from hayalab.classes.gumtree import AST, ASTNode
from hayalab.classes.pattern import Pattern
from hayalab.config.pattern_config import IDENTIFIER_NODE_TYPES, LITERAL_TYPE_MAP

# 抽象リテラルラベル → tree-sitter ノード名集合（detect 側照合用）。
_LITERAL_REVERSE: dict[str, set[str]] = {}
for _name, _label in LITERAL_TYPE_MAP.items():
    _LITERAL_REVERSE.setdefault(_label, set()).add(_name)


def _build_children_map(tree: list[ASTNode]) -> list[list[int]]:
    """各ノードの直接の子 index 列（出現順）を返す。

    Args:
        tree: AST ノード列（begin 昇順想定）。

    Returns:
        children[i] = node i の直接の子 index 列。
    """
    children: list[list[int]] = [[] for _ in range(len(tree))]
    for j, node in enumerate(tree):
        if node.parent:
            parent_idx = node.parent[-1]
            if 0 <= parent_idx < len(tree):
                children[parent_idx].append(j)
    return children


def _build_pattern_children(ast_template: list[dict]) -> tuple[list[list[int]], int | None]:
    """ast_template から local index ベースの子マップと root local index を返す。

    Args:
        ast_template: 抽象化済みノードの dict 列（origin_index 昇順）。

    Returns:
        (children_map, root_local_index)。root が見つからない場合 root は None。
    """
    n = len(ast_template)
    children: list[list[int]] = [[] for _ in range(n)]
    root_local: int | None = None
    for local_i, tn in enumerate(ast_template):
        parent_rel = tn.get("parent_relative", [])
        if not parent_rel:
            if root_local is None:
                root_local = local_i
            continue
        parent_local = parent_rel[-1]
        if 0 <= parent_local < n:
            children[parent_local].append(local_i)
    return children, root_local


def _passes_node_type_prefilter(pattern: Pattern, target_ast: AST) -> bool:
    """ノード型集合プリフィルタ。

    パターンが要求する各ノード型（抽象リテラルラベルは許容ノード型集合に展開）について、
    target AST にいずれかが存在することを確認する。識別子は target 側に `identifier` 系
    ノードがあれば成立とする（同一識別子整合性は AST 側で判定する）。
    """
    target_names = {n.name for n in target_ast.tree}
    has_identifier_in_target = bool(IDENTIFIER_NODE_TYPES & target_names)

    for tn in pattern.ast_template:
        name = tn["name"]
        slot_id = tn.get("slot_id")
        if slot_id is not None:
            if not has_identifier_in_target:
                return False
            continue
        # 抽象リテラルラベル (NUM, STR, BOOL, NULL, REGEX) は許容ノード型集合のうち
        # 少なくとも 1 つが target に存在することを要求
        if name in _LITERAL_REVERSE:
            if not (_LITERAL_REVERSE[name] & target_names):
                return False
            continue
        # 通常ノード（具体的な tree-sitter ノード型）は target に同名が存在する必要がある
        if name not in target_names:
            return False
    return True


def _match_node_label(
    p_node: dict,
    t_node: ASTNode,
    literal_generalize: bool,
    theta: dict[int, str],
) -> bool:
    """単一ノードのラベル照合（同一識別子の整合性チェック付き）。

    Args:
        p_node: パターン側ノード dict。
        t_node: 対象側 ASTNode。
        literal_generalize: True なら識別子は prefix-only 一致、False なら完全一致。
        theta: slot_id → target value のバインド辞書（破壊的更新する）。
    """
    p_name = p_node["name"]
    p_value = p_node["value"]
    slot_id = p_node.get("slot_id")
    prefix = p_node.get("prefix")
    original_value = p_node.get("original_value")

    # ── 抽象リテラルラベル (NUM/STR/BOOL/NULL/REGEX) ──
    if p_name in _LITERAL_REVERSE:
        return t_node.name in _LITERAL_REVERSE[p_name]

    # ── 識別子（slot ベース identity 保持） ──
    if slot_id is not None and prefix is not None:
        if t_node.name not in IDENTIFIER_NODE_TYPES:
            return False
        if literal_generalize:
            # A2/A3: プレフィクスのみ一致（PREFIX_* で任意 PREFIX_n を許容）
            if not t_node.value.startswith(prefix + "_"):
                return False
        else:
            # A0/A1: 元値完全一致
            if t_node.value != original_value:
                return False
        if slot_id in theta:
            if theta[slot_id] != t_node.value:
                return False
        else:
            theta[slot_id] = t_node.value
        return True

    # ── 通常ノード（構造ノード or 抽象化対象外の終端） ──
    if p_name != t_node.name:
        return False
    # value が空文字列ならワイルドカード相当
    if p_value and t_node.value and p_value != t_node.value:
        return False
    return True


def _match_children_strict(
    p_children: list[int],
    t_children: list[int],
    ast_template: list[dict],
    p_children_map: list[list[int]],
    t_tree: list[ASTNode],
    t_children_map: list[list[int]],
    literal_generalize: bool,
    theta: dict[int, str],
) -> bool:
    """厳密な子マッチ: パターンと target の子列長が一致し、順に対応する子がマッチする。"""
    if len(p_children) != len(t_children):
        return False
    for p_child, t_child in zip(p_children, t_children):
        snapshot = dict(theta)
        if not _match_subtree(
            p_child,
            t_child,
            ast_template,
            p_children_map,
            t_tree,
            t_children_map,
            literal_generalize,
            False,
            theta,
        ):
            theta.clear()
            theta.update(snapshot)
            return False
    return True


def _match_children_gap_tolerant(
    p_children: list[int],
    p_idx: int,
    t_children: list[int],
    t_pos: int,
    ast_template: list[dict],
    p_children_map: list[list[int]],
    t_tree: list[ASTNode],
    t_children_map: list[list[int]],
    literal_generalize: bool,
    theta: dict[int, str],
) -> bool:
    """Gap-tolerant 子マッチ: パターン側の子列が target 側に順序保存部分列として埋め込めるか。

    target 側に追加の子があっても OK（その子を skip して次を試す）。パターン側の全子は
    マッチする必要あり。失敗時は theta を巻き戻して別の対応関係を試す（再帰 backtrack）。
    """
    if p_idx >= len(p_children):
        return True
    p_child = p_children[p_idx]
    for t_idx in range(t_pos, len(t_children)):
        snapshot = dict(theta)
        if _match_subtree(
            p_child,
            t_children[t_idx],
            ast_template,
            p_children_map,
            t_tree,
            t_children_map,
            literal_generalize,
            True,
            theta,
        ):
            if _match_children_gap_tolerant(
                p_children,
                p_idx + 1,
                t_children,
                t_idx + 1,
                ast_template,
                p_children_map,
                t_tree,
                t_children_map,
                literal_generalize,
                theta,
            ):
                return True
        theta.clear()
        theta.update(snapshot)
    return False


def _match_subtree(
    p_local: int,
    t_idx: int,
    ast_template: list[dict],
    p_children_map: list[list[int]],
    t_tree: list[ASTNode],
    t_children_map: list[list[int]],
    literal_generalize: bool,
    gap_tolerant: bool,
    theta: dict[int, str],
) -> bool:
    """パターン部分木を対象部分木とマッチさせる（再帰）。"""
    p_node = ast_template[p_local]
    if not (0 <= t_idx < len(t_tree)):
        return False
    if not _match_node_label(p_node, t_tree[t_idx], literal_generalize, theta):
        return False

    pc = p_children_map[p_local]
    tc = t_children_map[t_idx]
    if gap_tolerant:
        return _match_children_gap_tolerant(
            pc,
            0,
            tc,
            0,
            ast_template,
            p_children_map,
            t_tree,
            t_children_map,
            literal_generalize,
            theta,
        )
    return _match_children_strict(
        pc,
        tc,
        ast_template,
        p_children_map,
        t_tree,
        t_children_map,
        literal_generalize,
        theta,
    )


def detect(pattern: Pattern, target_ast: AST, prefilter: bool = True) -> bool:
    """パターンが対象 AST 内に出現するか判定する。

    Args:
        pattern: 検出対象のパターン。
        target_ast: 対象 MB の AST。
        prefilter: True ならノード型集合プリフィルタで早期棄却（既定）。
            False の場合はプリフィルタを通さず全 target ノードに対して
            AST 部分木マッチングを試行する（フルマッチ）。

    Returns:
        マッチした場合 True。
    """
    if not pattern.ast_template:
        return False

    if prefilter and not _passes_node_type_prefilter(pattern, target_ast):
        return False

    literal_generalize = bool(pattern.abst_level >> 1)
    gap_tolerant = bool(pattern.abst_level & 1)

    p_children_map, root_local = _build_pattern_children(pattern.ast_template)
    if root_local is None:
        return False
    t_tree = target_ast.tree
    t_children_map = _build_children_map(t_tree)

    for t_idx in range(len(t_tree)):
        theta: dict[int, str] = {}
        if _match_subtree(
            root_local,
            t_idx,
            pattern.ast_template,
            p_children_map,
            t_tree,
            t_children_map,
            literal_generalize,
            gap_tolerant,
            theta,
        ):
            return True
    return False


def compute_detection(
    pattern: Pattern,
    dataset: Iterable[tuple[int, AST]],
    prefilter: bool = True,
) -> set[int]:
    """データセット全体に対する単一パターンの検出結果（マッチした MB id 集合）を計算する。

    Args:
        pattern: 検出対象のパターン。
        dataset: [(mb_id, ast), ...] のイテラブル。
        prefilter: ノード型集合プリフィルタを使うか（既定 True）。False でフルマッチ。

    Returns:
        マッチした mb_id の集合（検出結果）。
    """
    detection: set[int] = set()
    for mb_id, ast in dataset:
        if detect(pattern, ast, prefilter=prefilter):
            detection.add(mb_id)
    return detection
