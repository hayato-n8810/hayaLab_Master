"""Stage 2: 01_cutouts.json のフィルタリングと重複削除。

処理内容:
1) 内容空 cutout の除外
   ASTNode リストが「全て終端ノード（label に ':' を含む）」かつ
   「PUNCTUATION_NAMES または ABSTRACTION_PREFIXES のみで構成」されている
   cutout を除外する。空 nodes も除外。
2) 同一 id の 4 サイズ (Diff/Brother/ExParent/Parent) 内での重複削除
   nodes の origin_index 列が完全一致する cutout については
   より小さいサイズ (DEPTHS の先頭側) を残す。

入力: outputs/scam/approach/01_cutouts.json
出力:
    outputs/scam/approach/02_cutout_filter.json   フィルタ・dedup 後
    outputs/scam/approach/02_filter/excluded.json    除外された cutout 一覧
    outputs/scam/approach/02_filter/duplicates.json  重複削除された cutout 一覧
    outputs/scam/approach/02_filter/stats.json       02_cutout_filter.json 統計

実行例:
    uv run python experiments/scam/approach/02_filter.py
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path
from typing import Any

import hayalab
from hayalab.config import PathConfig

# 終端ノード判定用: ``"name: value [begin,end]"`` 形式にマッチ
_TERMINAL_LABEL_RE = re.compile(r"([^ ]+): (.+)")

# 小さいサイズ優先で残すための順序 (Diff ⊆ Brother ⊆ ExParent ⊆ Parent)
DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")

# 内容空判定に用いる汎用記号集合（loader.py と整合）
PUNCTUATION_NAMES: frozenset[str] = frozenset(["(", ")", ",", ".", ";", "{", "}", "[", "]", ":", '"', "'", "_"])

# 抽象化変数の prefix 集合（loader.py と整合）
ABSTRACTION_PREFIXES: tuple[str, ...] = ("VAR_", "LITERAL_", "FUNC_", "ARG_", "SLOT_")


def _is_terminal(node: dict[str, Any]) -> bool:
    """終端ノード判定: label が ``"name: value [...]"`` 形式にマッチする。

    01_cutouts.json では終端ノードは ``"name: value [begin,end]"``、
    非終端は ``"name [begin,end]"`` の形式で記録されているため、
    ``"name: value"`` の部分（name にスペース無し、value は任意）が
    含まれるかを正規表現で判定する。
    """
    return _TERMINAL_LABEL_RE.match(node.get("label", "")) is not None


def _is_punct_or_abst(node: dict[str, Any]) -> bool:
    """value/name が PUNCTUATION_NAMES または value が ABSTRACTION_PREFIXES で始まる。"""
    name = node.get("name", "")
    value = node.get("value", "")
    if name in PUNCTUATION_NAMES or value in PUNCTUATION_NAMES:
        return True
    return any(value.startswith(p) for p in ABSTRACTION_PREFIXES)


def is_content_free(nodes: list[dict[str, Any]]) -> bool:
    """cutout が内容空（除外対象）か判定する。

    Args:
        nodes: cutout の "nodes" リスト（生 dict）。

    Returns:
        全ノードが終端かつ punctuation/abstraction のみなら True。
        nodes が空でも True。
    """
    if not nodes:
        return True
    return all(_is_terminal(n) and _is_punct_or_abst(n) for n in nodes)


def _dedup_signature(cutout: dict[str, Any]) -> tuple[int, ...]:
    """cutout 同一性キー: nodes の origin_index 列（元順を保持）。"""
    return tuple(n["origin_index"] for n in cutout.get("nodes", []))


def filter_and_dedup_entry(
    entry: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """1 MB エントリにフィルタと dedup を適用する。

    Args:
        entry: ``{"id": int, "cutouts": {depth: {...}}}`` 形式の 1 件。

    Returns:
        (kept_cutouts, excluded_records, duplicate_records)
        - kept_cutouts: 残った cutout の dict (depth -> cutout)
        - excluded_records: 内容空で除外された記録
        - duplicate_records: dedup で削除された記録
    """
    mb_id = entry["id"]
    cutouts: dict[str, dict[str, Any]] = entry.get("cutouts", {})

    kept: dict[str, dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    seen_signatures: dict[tuple[int, ...], str] = {}

    for depth in DEPTHS:
        if depth not in cutouts:
            continue
        cutout = cutouts[depth]
        nodes = cutout.get("nodes", [])

        if is_content_free(nodes):
            excluded.append(
                {
                    "id": mb_id,
                    "depth": depth,
                    "reason": "content_free",
                    "node_count": len(nodes),
                }
            )
            continue

        sig = _dedup_signature(cutout)
        if sig in seen_signatures:
            duplicates.append(
                {
                    "id": mb_id,
                    "depth": depth,
                    "reason": "duplicate",
                    "node_count": len(nodes),
                    "kept_as": seen_signatures[sig],
                }
            )
            continue

        seen_signatures[sig] = depth
        kept[depth] = cutout

    return kept, excluded, duplicates


def _stats_of(values: list[int]) -> dict[str, Any]:
    """数値リストの基本統計。"""
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
    }


def build_stats(
    filtered_entries: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    original_mb_count: int,
) -> dict[str, Any]:
    """02_cutout_filter.json の統計情報を作成する。"""
    kept_per_depth: Counter[str] = Counter()
    node_count_by_depth: dict[str, list[int]] = {d: [] for d in DEPTHS}
    diff_idx_count_by_depth: dict[str, list[int]] = {d: [] for d in DEPTHS}
    depths_per_mb: list[int] = []

    for entry in filtered_entries:
        depths_per_mb.append(len(entry["cutouts"]))
        for depth, cutout in entry["cutouts"].items():
            kept_per_depth[depth] += 1
            node_count_by_depth[depth].append(len(cutout.get("nodes", [])))
            diff_idx_count_by_depth[depth].append(len(cutout.get("diff_node_indices", [])))

    total_kept = sum(kept_per_depth.values())
    return {
        "input": {
            "mb_count": original_mb_count,
            "cutouts_per_mb": len(DEPTHS),
            "total_cutouts": original_mb_count * len(DEPTHS),
        },
        "output": {
            "mb_count": len(filtered_entries),
            "kept_cutouts": total_kept,
            "kept_per_depth": {d: kept_per_depth.get(d, 0) for d in DEPTHS},
            "depths_per_mb_stats": _stats_of(depths_per_mb),
            "node_count_stats_per_depth": {d: _stats_of(node_count_by_depth[d]) for d in DEPTHS},
            "diff_node_indices_stats_per_depth": {d: _stats_of(diff_idx_count_by_depth[d]) for d in DEPTHS},
        },
        "excluded": {
            "count": len(excluded),
            "per_depth": {d: sum(1 for e in excluded if e["depth"] == d) for d in DEPTHS},
        },
        "duplicates": {
            "count": len(duplicates),
            "per_depth": {d: sum(1 for x in duplicates if x["depth"] == d) for d in DEPTHS},
            "kept_as_distribution": dict(Counter(x["kept_as"] for x in duplicates)),
        },
    }


def parse_args() -> argparse.Namespace:
    """CLI 引数。"""
    parser = argparse.ArgumentParser(description="Stage 2: filter & dedup cutouts")
    parser.add_argument("--input", type=Path, default=None, help="01_cutouts.json path")
    parser.add_argument("--output-dir", type=Path, default=None, help="output directory")
    return parser.parse_args()


def main() -> None:
    """Stage 2 を実行する。"""
    args = parse_args()
    pc = PathConfig()

    input_path = args.input or (pc.outputs / "scam" / "approach" / "01_cutouts.json")
    output_dir = args.output_dir or (pc.outputs / "scam" / "approach")
    output_dir.mkdir(parents=True, exist_ok=True)
    filter_dir = output_dir / "02_filter"
    filter_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")
    print(f"[INPUT] {input_path}", flush=True)

    records = hayalab.read_json(str(input_path))
    print(f"[RECORDS] {len(records)}", flush=True)

    filtered_entries: list[dict[str, Any]] = []
    all_excluded: list[dict[str, Any]] = []
    all_duplicates: list[dict[str, Any]] = []

    for entry in records:
        kept, excluded, duplicates = filter_and_dedup_entry(entry)
        all_excluded.extend(excluded)
        all_duplicates.extend(duplicates)
        if kept:
            filtered_entries.append({"id": entry["id"], "cutouts": kept})

    output_path = output_dir / "02_cutout_filter.json"
    hayalab.write_json(str(output_path), filtered_entries)

    excluded_path = filter_dir / "excluded.json"
    duplicates_path = filter_dir / "duplicates.json"
    stats_path = filter_dir / "stats.json"
    hayalab.write_json(str(excluded_path), all_excluded)
    hayalab.write_json(str(duplicates_path), all_duplicates)
    stats = build_stats(filtered_entries, all_excluded, all_duplicates, len(records))
    hayalab.write_json(str(stats_path), stats)

    print(f"[OUTPUT] {output_path}  (mb={len(filtered_entries)})", flush=True)
    print(f"[OUTPUT] {excluded_path}  (n={len(all_excluded)})", flush=True)
    print(f"[OUTPUT] {duplicates_path}  (n={len(all_duplicates)})", flush=True)
    print(f"[OUTPUT] {stats_path}", flush=True)


if __name__ == "__main__":
    main()
