"""MBDiff.json の base_actions ごとに，差分ノード周辺の base_ast ノードを切り出す。

切り出しロジックは ``hayalab.gumtree.cut`` にある。本スクリプトは入出力パスと
出力形式を定め，切り出しと同じ 1 パスで出力の健全性を検証する。

出力は 4 種類。

- レコード内の全 action の diff / parent_diff / around_parent をそれぞれ統合した JSON
  （``sigma_1.json`` / ``sigma_2.json`` / ``sigma_3.json``）
- 3 スコープを 1 本のノード列に畳み，各ノードに ``level`` を付与した JSONL

統合時は base_ast.tree の index 昇順に並べ，重複ノードは 1 件に畳む。

検証項目

- level 注釈の整合: ``level <= n`` のノード集合が第 n 段スコープに一致する
- 包含関係の保存: diff ⊆ parent_diff ⊆ around_parent
- 森の不変条件: 欠落祖先の解決，children，subtree_end（先頭 FOREST_SAMPLE 件）
- パス集合 / postorder の健全性（同上）
"""

from __future__ import annotations

import json

from tqdm import tqdm

import hayalab
from hayalab.classes.gumtree import CutForest, GumDiff
from hayalab.config import PathConfig
from hayalab.gumtree import build_cut_forest, cut_action_blocks, leveled_cut_nodes, merge_action_nodes, path_set, postorder_tree
from hayalab.gumtree.extract import NodePayload

# --- Constants (hyperparameters tunable at the top of the file) ----
# 森構築まで精査するレコード数（level 整合と包含関係は全件で検査する）
FOREST_SAMPLE: int = 3000

# スコープ段（level n = SCOPE_KEYS[n-1] まで含む）
SCOPE_KEYS: tuple[str, ...] = ("diff", "parent_diff", "around_parent")

# スコープ段と出力ファイル名の対応（SCOPE_KEYS と同順）
SIGMA_NAMES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")


# --- Helpers (only those called many times) ------------------------
def _verification_label(node: NodePayload) -> str:
    """検証用の比較ラベル（name と value を連結した具体ラベル）を返す。

    Args:
        node: ノード payload。

    Returns:
        ``name:value`` 形式のラベル。
    """
    return f"{node['name']}:{node['value']}"


def _check_forest(forest: CutForest, nodes: list[NodePayload]) -> list[str]:
    """CutForest の不変条件を検査し，違反メッセージのリストを返す。

    Args:
        forest: 検査対象の森。
        nodes: 構築元のノード payload 列（origin_index 昇順）。

    Returns:
        違反内容の説明文字列。違反がなければ空リスト。
    """
    errors: list[str] = []
    total = len(forest.labels)

    if total != len(nodes) + 1:
        errors.append(f"ノード数不一致: forest={total} nodes+1={len(nodes) + 1}")
    if forest.parent[0] != -1 or forest.origin_indices[0] != -1:
        errors.append("仮想ルートの parent / origin_index が -1 でない")
    if forest.subtree_end[0] != total - 1:
        errors.append("仮想ルートの subtree_end が末尾でない")

    present = {node["origin_index"] for node in nodes}
    for index in range(1, total):
        upper = forest.parent[index]
        if upper >= index:
            errors.append(f"親が自身より後ろ: index={index} parent={upper}")
        if forest.subtree_end[index] < index:
            errors.append(f"subtree_end が自身より小さい: index={index}")
        if index not in forest.children[upper]:
            errors.append(f"children に自身が含まれない: index={index}")
        # 解決された親は「元 parent 列のうち存在する最近接の祖先」であること
        ancestors = [a for a in nodes[index - 1]["parent"] if a in present]
        expected = forest.origin_indices.index(ancestors[-1]) if ancestors else 0
        if upper != expected:
            errors.append(f"親の解決が不正: index={index} got={upper} want={expected}")

    return errors


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    config = PathConfig()
    input_path = config.processed / "MBDiff.json"
    sigma_dir = config.outputs / "saner" / "approach" / "phase0"
    scope_paths = {key: sigma_dir / f"{name}.json" for key, name in zip(SCOPE_KEYS, SIGMA_NAMES, strict=True)}
    leveled_path = sigma_dir / "cut_leveled.jsonl"

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")
    sigma_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: 入力読み込み ---
    records = hayalab.read_json(str(input_path))
    print(f"Input:  {input_path} ({len(records)} records)")
    for path in (*scope_paths.values(), leveled_path):
        print(f"Output: {path}")

    # --- Section 3: 切り出し・書き出し・検証（1 パス） ---
    # 統合結果は JSON 配列を 1 レコードずつ書き足す（全件をメモリに保持しない）
    level_mismatch: list[int] = []
    nesting_violation: list[int] = []
    forest_errors: list[str] = []
    path_errors: list[int] = []
    postorder_errors: list[int] = []
    checked_forests = 0

    with (
        open(scope_paths["diff"], "w", encoding="utf-8") as f_diff,
        open(scope_paths["parent_diff"], "w", encoding="utf-8") as f_parent_diff,
        open(scope_paths["around_parent"], "w", encoding="utf-8") as f_around_parent,
        open(leveled_path, "w", encoding="utf-8") as f_leveled,
    ):
        scope_handles = {"diff": f_diff, "parent_diff": f_parent_diff, "around_parent": f_around_parent}
        for handle in scope_handles.values():
            handle.write("[\n")

        for order, item in enumerate(tqdm(records, total=len(records), desc="cut_gumtree_ast_diff")):
            record_id = item.get("id")
            diff_data = item.get("diff")
            blocks = cut_action_blocks(GumDiff.model_validate(diff_data)) if diff_data else []

            separator = "" if order == 0 else ",\n"
            scope_sets: list[set[int]] = []
            for key in SCOPE_KEYS:
                scope_nodes = merge_action_nodes(blocks, key)
                scope_sets.append({node["origin_index"] for node in scope_nodes})
                scope_handles[key].write(separator + json.dumps({"id": record_id, "nodes": scope_nodes}, ensure_ascii=False))

            leveled_nodes = leveled_cut_nodes(blocks)
            f_leveled.write(json.dumps({"id": record_id, "nodes": leveled_nodes}, ensure_ascii=False) + "\n")

            # 検証: level <= n の集合が第 n 段スコープに一致し，包含関係が保たれること
            leveled_sets = [{node["origin_index"] for node in leveled_nodes if node["level"] <= level} for level in (1, 2, 3)]
            if leveled_sets != scope_sets:
                level_mismatch.append(record_id)
            if not (leveled_sets[0] <= leveled_sets[1] <= leveled_sets[2]):
                nesting_violation.append(record_id)

            # 検証: 森の構築とパス集合 / postorder の健全性
            if checked_forests < FOREST_SAMPLE and leveled_nodes:
                checked_forests += 1
                forest = build_cut_forest(leveled_nodes, _verification_label)
                forest_errors.extend(f"id={record_id}: {message}" for message in _check_forest(forest, leveled_nodes))
                if len(path_set(forest)) > len(leveled_nodes):
                    path_errors.append(record_id)
                post = postorder_tree(forest)
                if sorted(post.labels) != sorted(forest.labels):
                    postorder_errors.append(record_id)
                elif any(post.leftmost[position] > position for position in range(len(post.labels))):
                    postorder_errors.append(record_id)

        for handle in scope_handles.values():
            handle.write("\n]\n")

    # --- Section 4: 検証結果の報告 ---
    for path in (*scope_paths.values(), leveled_path):
        print(f"Done: {path}")

    print(f"\n[検証] level 注釈の整合   : 不一致 {len(level_mismatch)} 件 {level_mismatch[:5]}")
    print(f"[検証] 包含関係の保存     : 違反 {len(nesting_violation)} 件 {nesting_violation[:5]}")
    print(f"[検証] 森の不変条件       : 違反 {len(forest_errors)} 件（検査 {checked_forests} 件）")
    for message in forest_errors[:5]:
        print(f"          {message}")
    print(f"[検証] パス集合           : 異常 {len(path_errors)} 件 {path_errors[:5]}")
    print(f"[検証] postorder          : 異常 {len(postorder_errors)} 件 {postorder_errors[:5]}")
