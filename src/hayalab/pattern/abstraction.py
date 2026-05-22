"""パターン抽出パイプライン Stage 2: 抽象化 (A0, A1, A2, A3)。

切り出し結果 (`Cutout`) と抽象化レベル (0..3) を受け取り、`Pattern` を返す。

抽象化レベル定義:
    - A0: データセット時点の表現を維持（識別子は VAR_n 既存正規化のまま、リテラル不変）
    - A1: 差分ノード集合 Δ の外側のリテラルのみを型クラス化（NUM, STR, BOOL, NULL, REGEX）
    - A2: A1 + R2-1 (Function 統一) + R2-3 (formal_parameters variadic) + R2-4 (VariableDeclaration 統一)
    - A3: A2 + Δ 内のリテラルも型クラス化

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
    FUNCTION_NODE_TYPES,
    IDENTIFIER_NODE_TYPES,
    IDENTIFIER_PREFIXES,
    LITERAL_TYPE_MAP,
    VARIABLE_DECLARATION_NODE_TYPES,
    VARIADIC_NODE_TYPES,
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

    Args:
        node: ASTNode。

    Returns:
        終端ノードなら True。
    """
    return node.label.startswith(f"{node.name}: ")


def _abstract_node(
    idx: int,
    node: ASTNode,
    in_diff: bool,
    abst_level: int,
    slot_lookup: dict[str, int],
) -> dict:
    """単一ノードを抽象化レベルに従って template dict に変換する。

    Args:
        idx: 元 AST における node の index。
        node: 元 ASTNode。
        in_diff: 差分ノード集合 Δ に含まれるか。
        abst_level: 抽象化レベル (0..3)。
        slot_lookup: original_value → slot_id のマップ（呼び出し側で構築・更新）。

    Returns:
        ast_template の 1 要素となる dict。
    """
    name = node.name
    value = node.value
    slot_id: int | None = None
    prefix: str | None = None
    original_value: str | None = None
    variadic = False

    # ── 識別子: A0–A3 共通で slot_id/prefix/original_value を保持 ─────────
    if name in IDENTIFIER_NODE_TYPES:
        prefix = _detect_identifier_prefix(value)
        if prefix is not None:
            original_value = value
            slot_id = slot_lookup.setdefault(value, len(slot_lookup) + 1)

    # ── リテラル汎化 (A1 / A3) ────────────────────────────────────────
    elif name in LITERAL_TYPE_MAP:
        abstract_label = LITERAL_TYPE_MAP[name]
        if abst_level >= 3 or (abst_level >= 1 and not in_diff):
            name = abstract_label
            value = abstract_label

    # ── 関数・宣言系の正規化 (A2 / A3) ────────────────────────────────
    # 終端の `function` キーワード（`function: function [...]`）と非終端 `function`
    # ノードは name が衝突するため、is_terminal 判定で非終端のみを正規化対象とする。
    is_terminal_node = _is_terminal_node(node)
    if abst_level >= 2 and not is_terminal_node:
        if node.name in FUNCTION_NODE_TYPES:
            name = "Function"
            value = "Function"
        elif node.name in VARIABLE_DECLARATION_NODE_TYPES:
            name = "VariableDeclaration"
            value = "VariableDeclaration"
        if node.name in VARIADIC_NODE_TYPES:
            variadic = True

    template_node: dict = {
        "origin_index": idx,
        "name": name,
        "value": value,
        "slot_id": slot_id,
        "prefix": prefix,
        "original_value": original_value,
        "variadic": variadic,
        "is_terminal": is_terminal_node,
    }
    return template_node


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
                "variadic": tn.get("variadic", False),
            }
        )
    payload = json.dumps(serializable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def abstract_cutout(cutout: Cutout, ast: AST, abst_level: int) -> Pattern:
    """切り出しに抽象化を適用してパターンを生成する。

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

    tree = ast.tree
    node_indices = cutout.node_indices
    diff_set = cutout.diff_node_indices

    # 元 AST index → cutout 内 local index (出現順)
    index_to_local: dict[int, int] = {idx: i for i, idx in enumerate(node_indices)}

    # 識別子 slot 割り当て: original_value → slot_id（Cutout 内で出現順に 1, 2, ...）
    slot_lookup: dict[str, int] = {}

    ast_template: list[dict] = []
    for idx in node_indices:
        node = tree[idx]
        in_diff = idx in diff_set
        tn = _abstract_node(idx, node, in_diff, abst_level, slot_lookup)
        # 元 AST の parent 列を Cutout 内 local index 列にマップ（Cutout 外の祖先は除外）
        tn["parent_relative"] = [index_to_local[p] for p in node.parent if p in index_to_local]
        ast_template.append(tn)

    signature = compute_signature(ast_template)

    return Pattern(
        mb_id=cutout.mb_id,
        depth=cutout.depth,
        abst_level=abst_level,
        ast_template=ast_template,
        signature=signature,
    )
