"""scam の slot 番号採番ヘルパーと punctuation 判定。

``hayalab.abst`` の前処理（VAR_*/FUNCTION_* 割り当て）を入力に、 cutout 内で
``$v0`` / ``$f0`` 形式の slot ID に再採番する純関数群。
"""

from __future__ import annotations

from typing import Any

# 抽象化結果から除外する汎用記号集合
PUNCTUATION_NAMES: frozenset[str] = frozenset(["(", ")", ",", ".", ";", "{", "}", "[", "]", ":", '"', "'", "_"])

# 入力 ``cutouts.json`` の前処理 (``hayalab.abst``) で割り当てられる
# identifier prefix → slot family marker の対応。
IDENTIFIER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("VAR_", "v"),
    ("FUNCTION_", "f"),
)

# L2 でリテラル抽象化対象となる tree-sitter ノード名。
LITERAL_NUMBER_NAME: str = "number"
LITERAL_STRING_FRAGMENT_NAME: str = "string_fragment"

# L2 で regex 配下抽象化のトリガーとなる tree-sitter ノード名。
REGEX_NODE_NAME: str = "regex"


def is_punctuation(node: dict[str, Any]) -> bool:
    """Punctuation ノードか判定する。

    Args:
        node: 入力ノード dict (``name`` / ``value`` を含む)。

    Returns:
        ``name`` または ``value`` が :data:`PUNCTUATION_NAMES` に含まれる場合 True。
    """
    return node["name"].strip() in PUNCTUATION_NAMES or node["value"].strip() in PUNCTUATION_NAMES


def match_identifier_prefix(value: str) -> tuple[str, str] | None:
    """Identifier prefix にマッチした場合 ``(prefix, marker)`` を返す。

    Args:
        value: ノードの ``value`` 文字列。

    Returns:
        例: ``"VAR_3"`` → ``("VAR_", "v")``。マッチしなければ ``None``。
    """
    for prefix, marker in IDENTIFIER_PREFIXES:
        if value.startswith(prefix):
            return prefix, marker
    return None


def allocate_slot(slot_map: dict[str, str], key: str, marker: str) -> str:
    """Slot ID を割り当てる（同一 key は同一 slot を再利用）。

    Args:
        slot_map: 同一 cutout 内で共有する mutable な slot 割当辞書。
        key: 元値（cache キー）。
        marker: slot family を示す 1 文字 (``v`` / ``f`` / ``n`` / ``s`` / ``r``)。

    Returns:
        ``$v0`` / ``$n1`` 等の slot ID。
    """
    if key in slot_map:
        return slot_map[key]
    count = sum(1 for v in slot_map.values() if v.startswith(f"${marker}"))
    slot_id = f"${marker}{count}"
    slot_map[key] = slot_id
    return slot_id
