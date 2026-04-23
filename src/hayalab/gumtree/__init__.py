"""GumTree関連API。"""

from .extract import base_diff_blocks, cut_diff_blocks, get_descendants, head_diff_blocks
from .gumtree_command import gum_diff, gum_parse
from .others import (
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
from .scan import collect_method_name, count_label, find_scope_boundary_index, nearest_ancestor_index_by_name

__all__ = [
    # gumreeコマンド
    "gum_parse",
    "gum_diff",

    # AST走査
    "count_label",
    "collect_method_name",
    "nearest_ancestor_index_by_name",
    "find_scope_boundary_index",

    # ASTの編集，抽出
    "get_descendants",
    "cut_diff_blocks",
    "base_diff_blocks",
    "head_diff_blocks",

    # 特徴抽出器(現在は非推奨)
    "DiffFeatureExtractor",
    "ExtractionContext",
    "FeatureExtractor",
    "ForStatementExtractor",
    "ForInStatementExtractor",
    "WhileStatementExtractor",
    "IfStatementExtractor",
    "PropertyIdentifierExtractor",
    "NewExpressionExtractor",
]
