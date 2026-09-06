"""宣言的なパターン仕様に基づく AST 部分木マッチング。

パターン仕様は JSON でノード制約の木として与えられ、フラット ASTNode 列に対して
部分木の包含を判定する。制約の意味論は ``_match_node`` / ``_match_sequence`` を参照。

宣言的にすることで，元の GumtreeDiff 形式から，変数名や構造などの抽象的なパターンを指定できるようになる。
"""

from __future__ import annotations

import re
from typing import Any

from hayalab.classes.gumtree import ASTNode, TreeContext, TreeMatch, TreePattern

DEFAULT_IGNORE_NAMES: frozenset[str] = frozenset({"(", ")", "[", "]", "{", "}", ",", ";", ".", '"', "'"})
# 出力ファイルに記述する元のプログラムのコード長
DEFAULT_SNIPPET_LIMIT: int = 1000


def load_tree_patterns(data: dict[str, Any]) -> list[TreePattern]:
    """パターン定義 JSON を TreePattern のリストに変換する。

    Args:
        data: パターン定義 JSON をパースした dict（``patterns`` キーを持つ）。

    Returns:
        pattern_id 昇順の TreePattern リスト。

    Raises:
        KeyError: 必須キー（``patterns`` / ``id`` / ``root``）が欠けている場合。
    """
    default_ignore = frozenset(data.get("ignore_names", DEFAULT_IGNORE_NAMES))
    patterns: list[TreePattern] = []
    for entry in data["patterns"]:
        ignore = frozenset(entry["ignore_names"]) if "ignore_names" in entry else default_ignore
        patterns.append(
            TreePattern(
                pattern_id=int(entry["id"]),
                key=entry.get("key", f"pattern_{entry['id']}"),
                description=entry.get("description", ""),
                root=entry["root"],
                ignore_names=ignore,
            )
        )
    return sorted(patterns, key=lambda p: p.pattern_id)


def build_tree_context(nodes: list[ASTNode], code: str, ignore_names: frozenset[str]) -> TreeContext:
    """フラット ASTNode 列から子索引と subtree 範囲を構築する。

    ``parent`` は根から自身の直前までの祖先インデックス列であり、末尾要素が直上の親。
    ノード列は preorder のため subtree は連続範囲になる。

    Args:
        nodes: ASTNode のリスト。
        code: ソースコード文字列。
        ignore_names: 子ノード列から除外するノード名の集合。

    Returns:
        構築された TreeContext。
    """
    n = len(nodes)
    children: list[list[int]] = [[] for _ in range(n)]
    subtree_end = list(range(n))
    for idx in range(n):
        parent = nodes[idx].parent
        if parent:
            children[parent[-1]].append(idx)
    for idx in range(n - 1, 0, -1):
        parent = nodes[idx].parent
        if parent and subtree_end[idx] > subtree_end[parent[-1]]:
            subtree_end[parent[-1]] = subtree_end[idx]
    return TreeContext(nodes=nodes, code=code, children=children, subtree_end=subtree_end, ignore_names=ignore_names)


def _match_constraint(constraint: Any, actual: str) -> bool:
    """単一フィールドの制約を評価する。

    制約は次の 4 形式を取る:
      - 省略（None）または ``"*"``: 任意
      - 文字列: 完全一致
      - 文字列リスト: いずれかに一致
      - ``{"regex": "..."}``: 正規表現の検索一致

    Args:
        constraint: 制約値。
        actual: 対象ノードの実値。

    Returns:
        制約を満たすなら True。

    Raises:
        ValueError: 制約が未対応の形式の場合。
    """
    if constraint is None or constraint == "*":
        return True
    if isinstance(constraint, str):
        return actual == constraint
    if isinstance(constraint, list):
        return actual in constraint
    if isinstance(constraint, dict) and "regex" in constraint:
        return re.search(constraint["regex"], actual) is not None
    raise ValueError(f"Unsupported constraint: {constraint!r}")


def _candidate_children(ctx: TreeContext, parent_idx: int, mode: str) -> list[int]:
    """子ノード仕様の候補インデックス列を返す。

    Args:
        ctx: マッチング用索引。
        parent_idx: 親ノードのインデックス。
        mode: ``"child"`` なら直下の子、``"descendant"`` なら subtree 全体。

    Returns:
        ignore_names を除外した候補インデックスの昇順リスト。
    """
    if mode == "descendant":
        raw = range(parent_idx + 1, ctx.subtree_end[parent_idx] + 1)
    else:
        raw = ctx.children[parent_idx]
    return [i for i in raw if ctx.nodes[i].name not in ctx.ignore_names]


def _match_sequence(
    ctx: TreeContext,
    parent_idx: int,
    specs: list[dict[str, Any]],
    spec_pos: int,
    min_idx: int,
    binds: dict[str, str],
) -> dict[str, str] | None:
    """子ノード仕様列を順序付き部分列としてマッチさせる（バックトラック付き）。

    仕様に書かれていない子ノードは読み飛ばされる。各仕様のマッチ位置は
    ノードインデックスの昇順（= ソース上の出現順）でなければならない。

    Args:
        ctx: マッチング用索引。
        parent_idx: 親ノードのインデックス。
        specs: 子ノード仕様のリスト。
        spec_pos: 現在評価中の仕様位置。
        min_idx: 次に選択できる最小のノードインデックス。
        binds: これまでに確定した捕捉名とテキストの対応。

    Returns:
        マッチした場合は更新後の binds、失敗した場合は None。
    """
    if spec_pos == len(specs):
        return binds
    spec = specs[spec_pos]
    for candidate in _candidate_children(ctx, parent_idx, spec.get("match", "child")):
        if candidate < min_idx:
            continue
        matched = _match_node(ctx, candidate, spec, dict(binds))
        if matched is None:
            continue
        result = _match_sequence(ctx, parent_idx, specs, spec_pos + 1, candidate + 1, matched)
        if result is not None:
            return result
    if spec.get("optional", False):
        return _match_sequence(ctx, parent_idx, specs, spec_pos + 1, min_idx, binds)
    return None


def _match_exact_children(
    ctx: TreeContext,
    parent_idx: int,
    specs: list[dict[str, Any]],
    binds: dict[str, str],
) -> dict[str, str] | None:
    """直下の子ノード列（ignore_names 除外後）と仕様列を 1 対 1 で照合する。

    Args:
        ctx: マッチング用索引。
        parent_idx: 親ノードのインデックス。
        specs: 子ノード仕様のリスト。
        binds: これまでに確定した捕捉名とテキストの対応。

    Returns:
        マッチした場合は更新後の binds、失敗した場合は None。
    """
    candidates = _candidate_children(ctx, parent_idx, "child")
    if len(candidates) != len(specs):
        return None
    current = binds
    for candidate, spec in zip(candidates, specs, strict=True):
        current = _match_node(ctx, candidate, spec, dict(current))
        if current is None:
            return None
    return current


def _match_node(
    ctx: TreeContext,
    idx: int,
    spec: dict[str, Any],
    binds: dict[str, str],
) -> dict[str, str] | None:
    """1 ノードに対してノード仕様を評価する。

    Args:
        ctx: マッチング用索引。
        idx: 対象ノードのインデックス。
        spec: ノード仕様。
        binds: これまでに確定した捕捉名とテキストの対応。

    Returns:
        マッチした場合は更新後の binds、失敗した場合は None。
    """
    node = ctx.nodes[idx]
    if not _match_constraint(spec.get("name"), node.name):
        return None
    if not _match_constraint(spec.get("value"), node.value):
        return None

    text = ctx.code[node.begin : node.end]
    if not _match_constraint(spec.get("text"), text):
        return None

    bind = spec.get("bind")
    if bind is not None:
        if bind in binds and binds[bind] != text:
            return None
        binds[bind] = text

    children_spec = spec.get("children")
    if children_spec is None:
        return binds
    if spec.get("children_mode", "subsequence") == "exact":
        return _match_exact_children(ctx, idx, children_spec, binds)
    return _match_sequence(ctx, idx, children_spec, 0, 0, binds)


def find_tree_matches(
    nodes: list[ASTNode],
    code: str,
    pattern: TreePattern,
    *,
    snippet_limit: int = DEFAULT_SNIPPET_LIMIT,
) -> list[TreeMatch]:
    """AST 全体から 1 パターンの部分木マッチを列挙する。

    Args:
        nodes: 対象 AST の ASTNode リスト。
        code: 対象 AST のソースコード文字列。
        pattern: マッチさせる TreePattern。
        snippet_limit: snippet の最大文字数。

    Returns:
        ノードインデックス昇順の TreeMatch リスト。
    """
    if not nodes:
        return []
    ctx = build_tree_context(nodes, code, pattern.ignore_names)
    results: list[TreeMatch] = []
    for idx in range(len(nodes)):
        if _match_node(ctx, idx, pattern.root, {}) is None:
            continue
        node = nodes[idx]
        results.append(
            TreeMatch(
                pattern_id=pattern.pattern_id,
                node_index=idx,
                begin=node.begin,
                end=node.end,
                snippet=code[node.begin : node.end][:snippet_limit],
            )
        )
    return results
