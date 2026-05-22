"""hayalab - JavaScriptマイクロベンチマークのAST差分解析とパターン抽出ライブラリ"""

# ファイルIO
# 抽象化
from .abst.abst import abst

# codeql関連
from .codeql.extract_code import extract_code_sarif
from .codeql.sarif_parse import parse_sarif
from .gumtree.extract import (
    base_diff_blocks,
    base_scope_block_exclude_parent,
    base_scope_block_include_parent,
    base_scope_brother,
    base_scope_diff,
    cut_diff_blocks,
    cut_scope_block_exclude_parent,
    cut_scope_block_include_parent,
    cut_scope_brother,
    cut_scope_diff,
    get_descendants,
    head_diff_blocks,
    head_scope_block_exclude_parent,
    head_scope_block_include_parent,
    head_scope_brother,
    head_scope_diff,
    node_to_payload,
)

# GumTree関連
from .gumtree.gumtree_command import gum_diff, gum_parse
from .gumtree.scan import collect_method_name, count_label, find_scope_boundary_index, find_sibling_root_indices

# パターン統合
from .pattern.integrate import integrate_features
from .pattern.others import (
    DoWhileStatementExtractor,
    ExtractionContext,
    FeatureExtractor,
    ForInStatementExtractor,
    ForStatementExtractor,
    IfStatementExtractor,
    NewExpressionExtractor,
    PropertyIdentifierExtractor,
    WhileStatementExtractor,
)

# 統計検定
from .stest.mann_whitney import mann_whitney_test

# AST関連
from .utils.ast import babel_parse
from .utils.file import read_file, read_json, write_file, write_json

__all__ = [
    # ファイルIO
    "read_file",
    "write_file",
    "read_json",
    "write_json",
    # AST
    "babel_parse",
    # 抽象化
    "abst",
    # GumTree
    "gum_parse",
    "gum_diff",
    "get_descendants",
    "cut_diff_blocks",
    "base_diff_blocks",
    "head_diff_blocks",
    "count_label",
    "collect_method_name",
    "find_scope_boundary_index",
    "find_sibling_root_indices",
    "node_to_payload",
    # スコープ切り出し（コア）
    "cut_scope_diff",
    "cut_scope_brother",
    "cut_scope_block_exclude_parent",
    "cut_scope_block_include_parent",
    # スコープ切り出し（base shortcut）
    "base_scope_diff",
    "base_scope_brother",
    "base_scope_block_exclude_parent",
    "base_scope_block_include_parent",
    # スコープ切り出し（head shortcut）
    "head_scope_diff",
    "head_scope_brother",
    "head_scope_block_exclude_parent",
    "head_scope_block_include_parent",
    # 特徴抽出器
    "ExtractionContext",
    "FeatureExtractor",
    "ForStatementExtractor",
    "ForInStatementExtractor",
    "WhileStatementExtractor",
    "DoWhileStatementExtractor",
    "IfStatementExtractor",
    "PropertyIdentifierExtractor",
    "NewExpressionExtractor",
    # パターン統合
    "integrate_features",
    # codeQL関連
    "extract_code_sarif",
    "parse_sarif",
    # 統計検定
    "mann_whitney_test",
]
