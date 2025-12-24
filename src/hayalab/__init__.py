"""hayalab - JavaScriptマイクロベンチマークのAST差分解析とパターン抽出ライブラリ"""

# ファイルIO
from .utils.file import read_file, read_json, write_file, write_json

# AST関連
from .utils.ast import babel_parse

# 抽象化
from .abst.abst import abst

# GumTree関連
from .gumtree.gumtree_command import gum_diff, gum_parse
from .gumtree.diff_block import base_diff_blocks, head_diff_blocks
from .gumtree.feature_extractor import DiffFeatureExtractor
from .gumtree.extractors import (
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
from .codeql.csv_parse import codeql_csv
from .codeql.extract_code import extract_code_block 

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
    # codeql関連
    "codeql_csv",
    "extract_code_block",
]
