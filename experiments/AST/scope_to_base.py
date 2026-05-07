"""各粒度のASTスコープを抽出して保存する。

実行すると4種類のスコープファイルを順次生成する：
  - scope_DIFF_BLOCK_targets.json         : 差分ノード + 配下
  - scope_BROTHER_DIFF_targets.json       : 差分ノードの直接親の子孫
  - scope_BLOCK_EXCLUDE_PARENT_targets.json : スコープ境界内の兄弟+差分ノードの部分木（境界自身を除く）
  - scope_BLOCK_INCLUDE_DIFF_targets.json : スコープ境界ノードの全子孫（境界自身を含む）
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from os import cpu_count
from typing import Any

from tqdm import tqdm

import hayalab
from hayalab.classes.gumtree import GumDiff
from hayalab.config import PathConfig
from hayalab.gumtree.extract import (
    base_scope_block_exclude_parent,
    base_scope_block_include_parent,
    base_scope_brother,
    base_scope_diff,
)

# スコープ境界とみなすノード名の集合
SCOPE_BOUNDARY: set[str] = {
    "program",  # トップレベルの全文（変数宣言・関数定義・式文など）
    # "statement_block",              # 粒度が大きい（他ノードを含有しすぎる）ので除外
    # ── ブロックレス可 制御構文 ─────────────────────────────
    "else_clause",  # else節の本体（statement_blockまたは単文）
    "if_statement",  # 条件部（parenthesized_expression）と then/else 本体
    "while_statement",  # 条件部（parenthesized_expression）とループ本体
    "do_statement",  # ループ本体と後置条件部（parenthesized_expression）
    "with_statement",  # with対象オブジェクトと本体
    "labeled_statement",  # ラベル付き文の本体
    "for_in_statement",  # ループ変数・イテラブル・本体（for-in / for-of）
    # ── switch ────────────────────────────────────────────
    "switch_case",  # case値（string/number）と各 case 節内の文群
    "switch_default",  # default 節内の文群
    "switch_body",  # switch全体のcase/default節リスト（{ }を含む）
    # ── for文（ヘッダー部と本体の両方を含む） ─────────────────
    "for_statement",  # 初期化・条件・更新（ヘッダー）とループ本体
    # ── 関数（アロー・式形式含む） ────────────────────────────
    "function",  # 関数宣言・関数式の引数リストと本体（statement_block）
    "arrow_function",  # 引数リスト・=>・本体（statement_blockまたは式）
    "function_declaration",  # 関数名・引数リスト・本体（statement_block）
    "function_expression",  # 無名/名前付き関数式の引数リスト・本体
    "generator_function_declaration",  # ジェネレータ関数名・*・引数リスト・本体
    "generator_function",  # ジェネレータ関数式の引数リスト・本体
    # ── 例外処理 ──────────────────────────────────────────
    "try_statement",  # try本体・catch節・finally節の全体
    "finally_clause",  # finally節の本体（statement_block）
    # ── クラス ────────────────────────────────────────────
    "class_body",  # クラス内のメソッド定義・フィールド定義の列
    "method_definition",  # メソッド名・引数リスト・本体（statement_block）
    "class_static_block",  # static { } ブロック内の文群
}


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
    return _wrap(item, base_scope_diff)


def _process_brother(item: dict[str, Any]) -> dict[str, Any]:
    return _wrap(item, base_scope_brother)


def _process_exclude_parent(item: dict[str, Any]) -> dict[str, Any]:
    return _wrap(item, lambda gd: base_scope_block_exclude_parent(gd, SCOPE_BOUNDARY))


def _process_include_parent(item: dict[str, Any]) -> dict[str, Any]:
    return _wrap(item, lambda gd: base_scope_block_include_parent(gd, SCOPE_BOUNDARY))


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

    input_path = config.data / "test_data" / "MBDiff_target.json"
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
            config.outputs / "AST" / "scope_DIFF_BLOCK_targets.json",
            _process_diff,
        ),
        (
            "scope_BROTHER_DIFF",
            config.outputs / "AST" / "scope_BROTHER_DIFF_targets.json",
            _process_brother,
        ),
        (
            "scope_BLOCK_EXCLUDE_PARENT",
            config.outputs / "AST" / "scope_BLOCK_EXCLUDE_PARENT_targets.json",
            _process_exclude_parent,
        ),
        (
            "scope_BLOCK_INCLUDE_DIFF",
            config.outputs / "AST" / "scope_BLOCK_INCLUDE_DIFF_targets.json",
            _process_include_parent,
        ),
    ]

    for name, output_path, processor in tasks:
        print(f"\n[{name}]")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = _run(records, processor, workers, desc=name)
        hayalab.write_json(str(output_path), result)
        print(f"  Output: {output_path} ({len(result)} entries)")
