"""各粒度のASTスコープを抽出して保存する（fast側）。

move-tree / update-node は base_actions にのみ記録されるため，
head_actions だけを走査するとこれらに対応する fast 側ノードが抜け落ちる．
matches（base ↔ head のノード対応表）で head 側インデックスに変換し
head_actions に補完してからスコープを切り出す．

実行すると4種類のスコープファイルを順次生成する：
  - scope_DIFF_BLOCK_targets.json
  - scope_BROTHER_DIFF_targets.json
  - scope_BLOCK_EXCLUDE_PARENT_targets.json
  - scope_BLOCK_INCLUDE_DIFF_targets.json
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from os import cpu_count
from typing import Any

from tqdm import tqdm

import hayalab
from hayalab.classes.gumtree import GumAction, GumDiff
from hayalab.config import PathConfig
from hayalab.gumtree.extract import (
    cut_scope_block_exclude_parent,
    cut_scope_block_include_parent,
    cut_scope_brother,
    cut_scope_diff,
)

# スコープ境界とみなすノード名の集合
SCOPE_BOUNDARY: set[str] = {
    "program",
    "else_clause",
    "if_statement",
    "while_statement",
    "do_statement",
    "with_statement",
    "labeled_statement",
    "for_in_statement",
    "switch_case",
    "switch_default",
    "switch_body",
    "for_statement",
    "function",
    "arrow_function",
    "function_declaration",
    "function_expression",
    "generator_function_declaration",
    "generator_function",
    "try_statement",
    "finally_clause",
    "class_body",
    "method_definition",
    "class_static_block",
}

# base_actions にのみ記録されるアクション種別
_MOVE_UPDATE: frozenset[str] = frozenset({"move-tree", "update-node"})


# ──────────────────────────────────────────────────────────
# move-tree / update-node の補完
# ──────────────────────────────────────────────────────────


def _augmented_head_actions(gum_diff: GumDiff) -> list[GumAction]:
    """head_actions に base 側の move-tree / update-node を補完して返す.

    move-tree と update-node は base_actions にのみ記録される．
    matches（base_index → head_index の対応表）で head 側インデックスを特定し，
    head_actions に含まれていないものを追加する．

    Args:
        gum_diff: 差分解析結果．

    Returns:
        補完済みの head_actions リスト．
    """
    match_map: dict[int, int] = {b: h for b, h in gum_diff.matches}
    head_tree_len = len(gum_diff.head_ast.tree)
    seen: set[int] = {a.index for a in gum_diff.head_actions if a.index is not None}

    extra: list[GumAction] = []
    for action in gum_diff.base_actions:
        if action.action not in _MOVE_UPDATE:
            continue
        head_idx = match_map.get(action.index)
        if head_idx is None or not (0 <= head_idx < head_tree_len):
            continue
        if head_idx in seen:
            continue
        extra.append(
            GumAction(
                action=action.action,
                tree=gum_diff.head_ast.tree[head_idx].label,
                index=head_idx,
            )
        )
        seen.add(head_idx)

    return gum_diff.head_actions + extra


# ──────────────────────────────────────────────────────────
# スコープ抽出（GumDiff → dict）
# ──────────────────────────────────────────────────────────


def _head_scope_diff(gum_diff: GumDiff) -> dict[str, Any]:
    return cut_scope_diff(gum_diff.head_ast, _augmented_head_actions(gum_diff))


def _head_scope_brother(gum_diff: GumDiff) -> dict[str, Any]:
    return cut_scope_brother(gum_diff.head_ast, _augmented_head_actions(gum_diff))


def _head_scope_excl(gum_diff: GumDiff) -> dict[str, Any]:
    return cut_scope_block_exclude_parent(gum_diff.head_ast, _augmented_head_actions(gum_diff), SCOPE_BOUNDARY)


def _head_scope_incl(gum_diff: GumDiff) -> dict[str, Any]:
    return cut_scope_block_include_parent(gum_diff.head_ast, _augmented_head_actions(gum_diff), SCOPE_BOUNDARY)


# ──────────────────────────────────────────────────────────
# レコード変換（ProcessPoolExecutor でピクルス可能なトップレベル関数）
# ──────────────────────────────────────────────────────────


def _wrap(item: dict[str, Any], extract_fn: Callable[[GumDiff], dict[str, Any]]) -> dict[str, Any]:
    record_id = item.get("id")
    diff_data = item.get("diff")
    if not diff_data:
        return {"id": record_id, "per_action": [], "merged": {"nodes": []}}
    gum_diff = GumDiff.model_validate(diff_data)
    return {"id": record_id, **extract_fn(gum_diff)}


def _process_diff(item: dict[str, Any]) -> dict[str, Any]:
    return _wrap(item, _head_scope_diff)


def _process_brother(item: dict[str, Any]) -> dict[str, Any]:
    return _wrap(item, _head_scope_brother)


def _process_exclude_parent(item: dict[str, Any]) -> dict[str, Any]:
    return _wrap(item, _head_scope_excl)


def _process_include_parent(item: dict[str, Any]) -> dict[str, Any]:
    return _wrap(item, _head_scope_incl)


# ──────────────────────────────────────────────────────────
# 共通並列実行
# ──────────────────────────────────────────────────────────


def _run(
    records: list[dict[str, Any]],
    processor: Callable[[dict[str, Any]], dict[str, Any]],
    workers: int,
    desc: str,
) -> list[dict[str, Any]]:
    if workers <= 1:
        return [processor(item) for item in tqdm(records, total=len(records), desc=desc)]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(tqdm(executor.map(processor, records), total=len(records), desc=desc))


if __name__ == "__main__":
    config = PathConfig()

    # input_path = config.data / "test_data" / "MBDiff_target.json"
    input_path = config.processed / "MBDiff.json"

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")

    WORKERS = 6
    workers = min(WORKERS, cpu_count() or 1)
    records = hayalab.read_json(str(input_path))

    print(f"Input:   {input_path} ({len(records)} records)")
    print(f"Workers: {workers}")

    tasks: list[tuple[str, Any, Callable]] = [
        (
            "scope_DIFF_BLOCK",
            config.outputs / "AST_HEAD" / "scope_DIFF_BLOCK_all.json",
            _process_diff,
        ),
        (
            "scope_BROTHER_DIFF",
            config.outputs / "AST_HEAD" / "scope_BROTHER_DIFF_all.json",
            _process_brother,
        ),
        (
            "scope_BLOCK_EXCLUDE_PARENT",
            config.outputs / "AST_HEAD" / "scope_BLOCK_EXCLUDE_PARENT_all.json",
            _process_exclude_parent,
        ),
        (
            "scope_BLOCK_INCLUDE_DIFF",
            config.outputs / "AST_HEAD" / "scope_BLOCK_INCLUDE_DIFF_all.json",
            _process_include_parent,
        ),
    ]

    for name, output_path, processor in tasks:
        print(f"\n[{name}]")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = _run(records, processor, workers, desc=name)
        hayalab.write_json(str(output_path), result)
        print(f"  Output: {output_path} ({len(result)} entries)")
