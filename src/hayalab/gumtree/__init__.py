"""GumTree関連API。"""

from .extract import (
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
from .gumtree_command import gum_diff, gum_parse
from .scan import collect_method_name, count_label, find_scope_boundary_index, find_sibling_root_indices

__all__ = [
    # gumtreeコマンド
    "gum_parse",
    "gum_diff",
    # AST走査
    "count_label",
    "collect_method_name",
    "find_scope_boundary_index",
    "find_sibling_root_indices",
    # ASTの編集，抽出
    "get_descendants",
    "cut_diff_blocks",
    "base_diff_blocks",
    "head_diff_blocks",
    # ノード payload 変換
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
]
