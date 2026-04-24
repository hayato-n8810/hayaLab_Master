"""hayalab - JavaScriptマイクロベンチマークのAST差分解析とパターン抽出ライブラリ"""

# ファイルIO
from .utils.file import read_file, read_json, write_file, write_json

# AST関連
from .utils.ast import babel_parse

# 抽象化
from .abst.abst import abst

# GumTree関連
from .gumtree.gumtree_command import gum_diff, gum_parse
from .gumtree.extract import base_diff_blocks, get_descendants, head_diff_blocks
from .gumtree.scan import collect_method_name, count_label, find_scope_boundary_index, nearest_ancestor_index_by_name
from .pattern.others import (
    DiffFeatureExtractor,
    ExtractionContext,
    FeatureExtractor,
    ForInStatementExtractor,
    ForStatementExtractor,
    IfStatementExtractor,
    NewExpressionExtractor,
    PropertyIdentifierExtractor,
    WhileStatementExtractor,
)

# パターン統合
from .pattern.integrate import integrate_features

# codeql関連
from .codeql.extract_code import extract_code_sarif
from .codeql.sarif_parse import parse_sarif


# 統計検定
from .stest.mann_whitney import mann_whitney_test

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
    "base_diff_blocks",
    "head_diff_blocks",
    "count_label",
    "collect_method_name",
    "DiffFeatureExtractor",
    # 特徴抽出器
    "ExtractionContext",
    "FeatureExtractor",
    "ForStatementExtractor",
    "ForInStatementExtractor",
    "WhileStatementExtractor",
    "IfStatementExtractor",
    "PropertyIdentifierExtractor",
    "NewExpressionExtractor",
    # パターン統合
    "integrate_features",
    "nearest_ancestor_index_by_name",
    "find_scope_boundary_index",
    "get_descendants",
    # codeQL関連
    "extract_code_sarif",
    "parse_sarif",
    # 統計検定
    "mann_whitney_test",
]
