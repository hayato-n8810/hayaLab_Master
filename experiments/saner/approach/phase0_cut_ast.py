"""MBDiff.json の base_actions ごとに，差分ノード周辺の base_ast ノードを切り出す。

切り出しロジックは ``hayalab.gumtree.cut`` にある。本スクリプトは入出力パスと
出力形式を定め，切り出しと同じ 1 パスで出力の健全性を検証する。

出力は 4 種類。

- レコード内の全 action の diff / parent_diff / around_parent をそれぞれ統合した JSON
  （``sigma_1.json`` / ``sigma_2.json`` / ``sigma_3.json``）
- スコープごとの切り出し規模の要約（``scope_size.json``）

統合時は base_ast.tree の index 昇順に並べ，重複ノードは 1 件に畳む。

``node_count`` は区切り記号を除いた切り出しノード数であり，``scope_size.json`` は
その分布と，差分ノード（第 1 段スコープ）に由来しないノードの割合の分布をまとめる。
"""

from __future__ import annotations

import json
import statistics

from tqdm import tqdm

import hayalab
from hayalab.classes.gumtree import GumDiff
from hayalab.config import PathConfig
from hayalab.gumtree import cut_action_blocks, merge_action_nodes

# --- Constants (hyperparameters tunable at the top of the file) ----
# 森構築まで精査するレコード数（level 整合と包含関係は全件で検査する）
FOREST_SAMPLE: int = 3000

# スコープ段（level n = SCOPE_KEYS[n-1] まで含む）
SCOPE_KEYS: tuple[str, ...] = ("diff", "parent_diff", "around_parent")

# スコープ段と出力ファイル名の対応（SCOPE_KEYS と同順）
SIGMA_NAMES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")

# 親ノードの型から一意に定まる区切り記号（node_count の対象外）。演算子は含めない
DELIMITER_NAMES: frozenset[str] = frozenset({"(", ")", "[", "]", "{", "}", ",", ";", ".", '"', "'", "`", ":", "=>", "${"})


# --- Helpers (only those called multiple times) --------------------
def _counted_indices(nodes: list[dict]) -> set[int]:
    """区切り記号を除いた切り出しノードの ``origin_index`` 集合を返す。

    Args:
        nodes: 統合済みのノード payload 列。

    Returns:
        ``origin_index`` の集合。区切り記号のみの場合は空集合。
    """
    return {node["origin_index"] for node in nodes if node["name"] not in DELIMITER_NAMES}


def _quantile(sorted_values: list[float], q: float) -> float:
    """昇順に並んだ値列の分位点を線形補間で返す。

    Args:
        sorted_values: 昇順に並んだ値の列。空であってはならない。
        q: 0.0 以上 1.0 以下の分位。

    Returns:
        分位点の値。
    """
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = q * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return float(sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight)


def _summary(values: list[float]) -> dict[str, float]:
    """値列の平均・中央値・四分位・分散をまとめる。

    Args:
        values: 集計対象の値列。空であってはならない。

    Returns:
        ``mean`` / ``median`` / ``q1`` / ``q3`` / ``variance`` / ``min`` / ``max`` を持つ辞書。

    Raises:
        ValueError: ``values`` が空の場合。
    """
    if not values:
        raise ValueError("集計対象の値がありません")
    ordered = sorted(float(value) for value in values)
    return {
        "mean": statistics.mean(ordered),
        "median": statistics.median(ordered),
        "q1": _quantile(ordered, 0.25),
        "q3": _quantile(ordered, 0.75),
        "variance": statistics.pvariance(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    config = PathConfig()
    input_path = config.processed / "MBDiff.json"
    sigma_dir = config.outputs / "saner" / "approach" / "phase0"
    scope_paths = {key: sigma_dir / f"{name}.json" for key, name in zip(SCOPE_KEYS, SIGMA_NAMES, strict=True)}

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")
    sigma_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: 入力読み込み ---
    records = hayalab.read_json(str(input_path))
    print(f"Input:  {input_path} ({len(records)} records)")

    # --- Section 3: 切り出し・書き出し・検証（1 パス） ---
    # 統合結果は JSON 配列を 1 レコードずつ書き足す（全件をメモリに保持しない）
    level_mismatch: list[int] = []
    nesting_violation: list[int] = []
    forest_errors: list[str] = []
    path_errors: list[int] = []
    postorder_errors: list[int] = []
    checked_forests = 0

    # scope_size.json の集計用（レコード単位のノード数と非差分ノード比）
    node_counts: dict[str, list[int]] = {key: [] for key in SCOPE_KEYS}
    non_diff_ratios: dict[str, list[float]] = {key: [] for key in SCOPE_KEYS}
    pooled_nodes: dict[str, int] = {key: 0 for key in SCOPE_KEYS}
    pooled_non_diff: dict[str, int] = {key: 0 for key in SCOPE_KEYS}

    with (
        open(scope_paths["diff"], "w", encoding="utf-8") as f_diff,
        open(scope_paths["parent_diff"], "w", encoding="utf-8") as f_parent_diff,
        open(scope_paths["around_parent"], "w", encoding="utf-8") as f_around_parent,
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
            diff_indices: set[int] = set()
            for key in SCOPE_KEYS:
                scope_nodes = merge_action_nodes(blocks, key)
                scope_sets.append({node["origin_index"] for node in scope_nodes})

                counted = _counted_indices(scope_nodes)
                if key == SCOPE_KEYS[0]:
                    diff_indices = counted
                if counted:
                    non_diff = len(counted - diff_indices)
                    node_counts[key].append(len(counted))
                    non_diff_ratios[key].append(non_diff / len(counted))
                    pooled_nodes[key] += len(counted)
                    pooled_non_diff[key] += non_diff

                record = {"id": record_id, "node_count": len(counted), "nodes": scope_nodes}
                scope_handles[key].write(separator + json.dumps(record, ensure_ascii=False))

        for handle in scope_handles.values():
            handle.write("\n]\n")

    # --- Section 4: 切り出し規模の集計 ---
    scope_rows: list[dict] = []
    for key, name in zip(SCOPE_KEYS, SIGMA_NAMES, strict=True):
        if not node_counts[key]:
            raise ValueError(f"集計対象のレコードがありません: {name}")
        scope_rows.append(
            {
                "scope": name,
                "records": len(node_counts[key]),
                "nodes_total": pooled_nodes[key],
                "nodes": _summary(node_counts[key]),
                "non_diff_ratio": _summary(non_diff_ratios[key]),
            }
        )
        print(
            f"{name}: {len(node_counts[key])} records  "
            f"nodes mean {scope_rows[-1]['nodes']['mean']:.1f} / median {scope_rows[-1]['nodes']['median']:.0f}  "
            f"non_diff mean {scope_rows[-1]['non_diff_ratio']['mean']:.3f} / median {scope_rows[-1]['non_diff_ratio']['median']:.3f}"
        )

    scope_size_path = sigma_dir / "scope_size.json"
    with open(scope_size_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "diff_base_scope": SIGMA_NAMES[0],
                "delimiter_names": sorted(DELIMITER_NAMES),
                "scopes": scope_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Done: {len(records)} records")
    for path in (*scope_paths.values(), scope_size_path):
        print(f"Output: {path}")
