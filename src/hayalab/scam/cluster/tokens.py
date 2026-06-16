"""Cutout のノード列からトークン列・n-gram・bigram 集合を構築する純関数群。

トークン化規約:

* 各ノードを ``(name, normalize_value(value))`` の 2 要素タプルに縮約。
* value は slot タイプのみに正規化 (``$v0`` → ``$v`` 等、 prefix v/f/k/n/s)。
  ``$api`` は番号なしのため素通し。
* ``variadic=True`` のノードは集約鍵から除外する（子サブツリーは含む）。
"""

from __future__ import annotations

import re

# cutout depth の順序（出力スキーマ安定化のため固定）。
DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")

# slot 番号正規化: ``$v0`` → ``$v``。prefix v/f/k/n/s に続く数字を捨てる。
# ``$api`` は数字を持たないためマッチせず素通しになる。
_SLOT_NUM_RE = re.compile(r"^\$([vfkns])\d+$")


def normalize_value(value: str | None) -> str:
    """Slot 番号を捨てて slot タイプのみに正規化する。

    Args:
        value: ノードの ``value`` 文字列（``None`` 可）。

    Returns:
        ``$v0`` → ``$v`` のように slot 番号を除いた値。具体値はそのまま、
        ``None`` は空文字列。
    """
    if value is None:
        return ""
    m = _SLOT_NUM_RE.match(value)
    if m:
        return f"${m.group(1)}"
    return value


def node_token(node: dict) -> tuple[str, str]:
    """ノード dict を canonical な ``(name, normalized_value)`` タプルに縮約する。"""
    return (node["name"], normalize_value(node.get("value")))


def tokens_from_nodes(nodes: list[dict]) -> list[tuple[str, str]]:
    """``variadic=True`` のノードを除外したトークン列を返す。"""
    return [node_token(n) for n in nodes if not n.get("variadic", False)]


def ngrams(tokens: list[tuple[str, str]], n: int) -> list[tuple]:
    """トークン列から n-gram（n 個連続トークンのタプル）の列を返す。"""
    if len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def bigrams_from_nodes(nodes: list[dict]) -> frozenset[tuple[tuple[str, str], tuple[str, str]]]:
    """ノード列から bigram frozenset を返す（クラスタ生成と同一定義）。

    ``variadic=True`` のノードは除外する。 有効トークン数 < 2 のときは空集合。
    """
    toks = tokens_from_nodes(nodes)
    if len(toks) < 2:
        return frozenset()
    return frozenset(tuple(toks[i : i + 2]) for i in range(len(toks) - 1))
