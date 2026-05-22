"""パターン抽出パイプライン Stage 2: 抽象化 (A0, A1, A2, A3)。

抽象化レベルを 2 軸 × 2 値の組合せで定義する:

| level | bits | literal_generalize | gap_tolerant | クローン型相当 |
|---|---|---|---|---|
| A0 | 0b00 | False | False | Type-1 |
| A1 | 0b01 | False | True  | Type-3 (構造のみ寛容) |
| A2 | 0b10 | True  | False | Type-2 |
| A3 | 0b11 | True  | True  | Type-3 (Type-2 + 構造寛容) |

- 軸1 (literal_generalize) = `abst_level >> 1`: 値レベルの汎化
    - リテラル (number, string, true/false, null/undefined, regex) を型クラスに置換
    - 識別子のマッチ規則: A0/A1 = 元値完全一致、A2/A3 = プレフィクスのみ一致 (detect 側で実装)
- 軸2 (gap_tolerant) = `abst_level & 1`: マッチング側の寛容さ（detect 側で実装）

公開 API:
    - abstract_cutout(cutout, ast, abst_level): Pattern
    - compute_signature(ast_template): str
"""

from __future__ import annotations

import hashlib
import json

from hayalab.classes.gumtree import AST, ASTNode
from hayalab.classes.pattern import Cutout, Pattern
from hayalab.config.pattern_config import (
    IDENTIFIER_NODE_TYPES,
    IDENTIFIER_PREFIXES,
    LITERAL_TYPE_MAP,
)


def _detect_identifier_prefix(value: str) -> str | None:
    """Value の先頭プレフィクス（VAR/KEY/FUNCTION/CLASS）を返す。なければ None。"""
    for prefix_str, prefix_class in IDENTIFIER_PREFIXES.items():
        if value.startswith(prefix_str):
            return prefix_class
    return None


def _is_terminal_node(node: ASTNode) -> bool:
    """終端ノードか判定する。

    tree-sitter の label 形式に依存する: 終端ノードは `"name: value [begin,end]"`
    という形式の label を持ち、非終端ノードは `"name [begin,end]"` のみで `: value`
    の部分を持たない。記号類 (`(`, `;`, `=` 等) は `name == value` だが `label` に
    `: value` 部分があるため終端として識別される。
    """
    return node.label.startswith(f"{node.name}: ")


def _abstract_node(
    idx: int,
    node: ASTNode,
    literal_generalize: bool,
    slot_lookup: dict[str, int],
) -> dict:
    """単一ノードを抽象化レベルに従って template dict に変換する。

    Args:
        idx: 元 AST における node の index。
        node: 元 ASTNode。
        literal_generalize: True ならリテラルを型クラスに置換する（A2/A3 相当）。
        slot_lookup: original_value → slot_id のマップ（呼び出し側で構築・更新）。

    Returns:
        ast_template の 1 要素となる dict。
    """
    name = node.name
    value = node.value
    slot_id: int | None = None
    prefix: str | None = None
    original_value: str | None = None
    is_terminal = _is_terminal_node(node)

    # ── 識別子: 全レベルで slot_id/prefix/original_value を保持（マッチ規則は detect 側で分岐） ──
    if name in IDENTIFIER_NODE_TYPES:
        prefix = _detect_identifier_prefix(value)
        if prefix is not None:
            original_value = value
            slot_id = slot_lookup.setdefault(value, len(slot_lookup) + 1)

    # ── リテラル汎化 (A2/A3 = literal_generalize=True) ──
    elif literal_generalize and name in LITERAL_TYPE_MAP:
        abstract_label = LITERAL_TYPE_MAP[name]
        name = abstract_label
        value = abstract_label

    return {
        "origin_index": idx,
        "name": name,
        "value": value,
        "slot_id": slot_id,
        "prefix": prefix,
        "original_value": original_value,
        "is_terminal": is_terminal,
    }


def compute_signature(ast_template: list[dict]) -> str:
    """ast_template から決定論的にハッシュ署名を計算する。

    Args:
        ast_template: 抽象化済みノードの dict 列（ノード origin_index 昇順）。

    Returns:
        SHA-256 の先頭 16 文字。
    """
    serializable = []
    for tn in ast_template:
        serializable.append(
            {
                "name": tn["name"],
                "value": tn["value"],
                "parent_relative": tn.get("parent_relative", []),
                "slot_id": tn.get("slot_id"),
            }
        )
    payload = json.dumps(serializable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def abstract_cutout(cutout: Cutout, ast: AST, abst_level: int) -> Pattern:
    """切り出しに抽象化を適用してパターンを生成する。

    abst_level のビット解釈:
        - bit 1 (literal_generalize): リテラルを型クラスに置換、識別子は prefix-only マッチ
        - bit 0 (gap_tolerant): 子マッチを gap-tolerant 化（detect 側で参照）

    Args:
        cutout: 切り出し結果。
        ast: 元 AST（cutout.node_indices が参照する）。
        abst_level: 抽象化レベル (0..3)。

    Returns:
        抽象化適用後のパターン。signature は決定論的に計算される。

    Raises:
        ValueError: abst_level が 0..3 の範囲外、もしくは node_indices が空。
    """
    if abst_level not in (0, 1, 2, 3):
        raise ValueError(f"abst_level must be one of 0..3, got {abst_level}")
    if not cutout.node_indices:
        raise ValueError("Cutout has no node_indices")

    literal_generalize = bool(abst_level >> 1)
    tree = ast.tree
    node_indices = cutout.node_indices

    # 元 AST index → cutout 内 local index (出現順)
    index_to_local: dict[int, int] = {idx: i for i, idx in enumerate(node_indices)}

    # 識別子 slot 割り当て: original_value → slot_id（Cutout 内で出現順に 1, 2, ...）
    slot_lookup: dict[str, int] = {}

    ast_template: list[dict] = []
    for idx in node_indices:
        tn = _abstract_node(idx, tree[idx], literal_generalize, slot_lookup)
        # 元 AST の parent 列を Cutout 内 local index 列にマップ（Cutout 外の祖先は除外）
        tn["parent_relative"] = [index_to_local[p] for p in tree[idx].parent if p in index_to_local]
        ast_template.append(tn)

    signature = compute_signature(ast_template)

    return Pattern(
        mb_id=cutout.mb_id,
        depth=cutout.depth,
        abst_level=abst_level,
        ast_template=ast_template,
        signature=signature,
    )
