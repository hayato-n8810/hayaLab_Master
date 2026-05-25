"""パターン抽出パイプライン用の設定値。

`SCOPE_BOUNDARY` は L3/L4 の境界判定にのみ用いる。`statement_block` を意図的に除外しているため、
`if (cond) { ... }` であれば L4 = `if_statement` となり、`statement_block` 中身ではない。

抽象化用のリテラル種別マップ、識別子プレフィクスマップを定義する。
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────
# L3/L4 のスコープ境界判定（既存 experiments/AST/scope_to_base.py の SCOPE_BOUNDARY と整合）
# ──────────────────────────────────────────────────────────
SCOPE_BOUNDARY: set[str] = {
    "program",
    # ── ブロックレス可 制御構文 ─────────────────────────────
    "else_clause",
    "if_statement",
    "while_statement",
    "do_statement",
    "with_statement",
    "labeled_statement",
    "for_in_statement",
    # ── switch ────────────────────────────────────────────
    "switch_case",
    "switch_default",
    "switch_body",
    # ── for文 ─────────────────────────────────────────────
    "for_statement",
    # ── 関数（アロー・式形式含む） ────────────────────────────
    "function",
    "arrow_function",
    "function_declaration",
    "function_expression",
    "generator_function_declaration",
    "generator_function",
    # ── 例外処理 ──────────────────────────────────────────
    "try_statement",
    "catch_clause",
    "finally_clause",
    # ── クラス ────────────────────────────────────────────
    "class_declaration",
    "class",
    "class_body",
    "method_definition",
    "class_static_block",
}


# ──────────────────────────────────────────────────────────
# 抽象化用ラベル: tree-sitter JS の named ノード型 → 抽象クラス
# ──────────────────────────────────────────────────────────

# A2/A3 (literal_generalize=True) でリテラルを汎化する対象。
LITERAL_TYPE_MAP: dict[str, str] = {
    "number": "NUM",
    "string": "STR",
    "template_string": "STR",
    "string_fragment": "STR",
    "true": "BOOL",
    "false": "BOOL",
    "null": "NULL",
    "undefined": "NULL",
    "regex": "REGEX",
}

FUNCTION_LIKE_TYPES: set[str] = {"arrow_function", "function_expression", "function_declaration", "generator_function", "generator_function_declaration", "method_definition"}
FUNCTION_LIKE_LABEL: str = "FUNCTION_LIKE"


# ──────────────────────────────────────────────────────────
# 識別子（プレフィクスベース identity 保持）
# ──────────────────────────────────────────────────────────

# `value` 先頭のプレフィクス文字列 → クラス。
IDENTIFIER_PREFIXES: dict[str, str] = {
    "VAR_": "VAR",
    "KEY_": "KEY",
    "FUNCTION_": "FUNCTION",
    "CLASS_": "CLASS",
}

# 識別子相当の tree-sitter named ノード型。
IDENTIFIER_NODE_TYPES: set[str] = {
    "identifier",
    "property_identifier",
    "shorthand_property_identifier",
    "shorthand_property_identifier_pattern",
}


# ──────────────────────────────────────────────────────────
# デフォルト閾値
# ──────────────────────────────────────────────────────────

# 同値類集約 Jaccard 閾値（デフォルト 1.0 = 完全一致）。
DEFAULT_TAU: float = 1.0

# サイズスコアの ρ 重み w ∈ [0, 1]（デフォルト中間値）。
DEFAULT_WEIGHT_W: float = 0.5
