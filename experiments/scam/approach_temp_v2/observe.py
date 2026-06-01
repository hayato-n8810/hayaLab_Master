"""集約結果から trajectory と classes_*.json を構築する.

approach_temp/observe.py のサブセット．aggregate.md ベースの M0/M1/M2/M3
を比較するため、出力スキーマは approach_temp と互換に揃える．

Output schema:

``classes_A{level}_{method}.json``::

    [
      {
        "class_id": "L{level}_{method}_{hash}",
        "abst_level": <int>,
        "method": "<M0|M1|M2|M3>",
        "size": <int>,
        "members": [<cutout_id>...],
        "depth_profile": {"Diff": n, "Brother": n, ...},
        "representative_ast": [<TemplateNode dict>...]
      },
      ...
    ]

``trajectory_{method}.json``::

    [{"cutout_id": "...", "mb_id": ..., "depth": "...", "trajectory": {"0": class_id_L0, "1": ..., "2": ..., "3": ...}}, ...]
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from ast_node import Pattern
from cluster import nodes_to_tree
from methods import m0_ordered_hash, m1_seq_bigram, m2_path_ngram, m3_antiunify

logger = logging.getLogger(__name__)

LEVELS = (0, 1, 2, 3)
DEPTHS = ("Diff", "Brother", "ExParent", "Parent")


# ---------------------------------------------------------------------------
# 集約手法ディスパッチ
# ---------------------------------------------------------------------------


def _dispatch_cluster(
    method: str,
    patterns: list[Pattern],
    params: dict | None = None,
) -> dict[str, list[str]]:
    """Run the selected method and return class → members mapping."""
    params = params or {}
    workers = int(params.get("workers", 1))
    if method == "M0":
        return m0_ordered_hash.cluster_m0(patterns, workers=workers)
    if method == "M1":
        # M1/M2 のトークン化は (name, normalized_value) のみで、
        # parent_name 等の補助情報は使わない (M1 docstring 参照)．
        return m1_seq_bigram.cluster_m1(
            patterns,
            mode=params.get("m1_mode", "exact"),
            tau_jaccard=params.get("m1_tau_jaccard", 0.7),
            workers=workers,
        )
    if method == "M2":
        return m2_path_ngram.cluster_m2(
            patterns,
            n_value=params.get("m2_n", 2),
            mode=params.get("m2_mode", "exact"),
            tau_jaccard=params.get("m2_tau_jaccard", 0.7),
            workers=workers,
        )
    if method == "M3":
        # M3 LGG: ペア sim 計算は chunk 並列化（workers > 1）．chunk 結果は
        # i_start 順に結合されるため、workers の値によらず candidates list が
        # 逐次経路と bit-identical になり、結果クラス分割も同一．
        return m3_antiunify.cluster_m3(
            patterns,
            tau_sim=params.get("m3_tau_sim", 0.5),
            kappa=params.get("m3_kappa", 3.0),
            rho=params.get("m3_rho", 0.5),
            workers=workers,
        )
    raise ValueError(f"Unknown method: {method!r}")


# ---------------------------------------------------------------------------
# 代表 AST の決定
# ---------------------------------------------------------------------------


def _pick_representative_ast(
    method: str,
    class_id: str,
    members: list[str],
    pattern_by_id: dict[str, Pattern],
) -> list[dict]:
    """Choose a representative AST for the class.

    * M3: anti-unification の LGG 木が ``cluster_m3.last_representatives`` に
      格納されているため、それを TemplateNode dict 列にシリアライズする．
    * M0/M1/M2: 完全一致 / 部分一致集約のため、メンバの先頭 cutout の
      ``ast_template`` をそのまま代表として使う（exact mode では同一構造）．
    """
    if method == "M3":
        reps = getattr(m3_antiunify.cluster_m3, "last_representatives", None)
        tree = reps.get(class_id) if reps else None
        if tree is not None:
            return _treenode_to_dicts(tree)

    # Fallback: pick the first member's ast_template
    if not members:
        return []
    p = pattern_by_id.get(members[0])
    if p is None:
        return []
    return [n.to_dict() for n in p.ast_template]


def _treenode_to_dicts(tree) -> list[dict]:
    """Flatten a TreeNode into the TemplateNode-dict list used downstream.

    parent_relative is reconstructed as the indices of ancestor nodes in the
    DFS-emit order (synthetic indices).  ``slot_id`` is ``"$slot"`` for slot
    nodes, otherwise None.
    """
    nodes: list[dict] = []
    counter = [0]

    def _walk(t, parent_path: list[int]) -> None:
        idx = counter[0]
        counter[0] += 1
        nodes.append(
            {
                "origin_index": idx,
                "name": t.name,
                "value": t.value,
                "parent_relative": list(parent_path),
                "slot_id": "$slot" if t.is_slot else None,
                "is_terminal": not t.children,
                "variadic": t.variadic,
            }
        )
        new_parent_path = parent_path + [idx]
        for c in t.children:
            _walk(c, new_parent_path)

    _walk(tree, [])
    return nodes


# ---------------------------------------------------------------------------
# クラスタの永続化
# ---------------------------------------------------------------------------


def save_classes(
    classes: dict[str, list[str]],
    method: str,
    level: int,
    patterns: list[Pattern],
    output_dir: Path,
) -> None:
    """Save ``classes_A{level}_{method}.json`` with depth_profile and rep AST."""
    pattern_by_id: dict[str, Pattern] = {p.cutout_id: p for p in patterns}

    records: list[dict] = []
    for class_id, members in sorted(classes.items()):
        depth_profile: Counter[str] = Counter()
        for cid in members:
            p = pattern_by_id.get(cid)
            if p is not None:
                depth_profile[p.depth] += 1
        rec = {
            "class_id": class_id,
            "abst_level": level,
            "method": method,
            "size": len(members),
            "members": list(members),
            "depth_profile": dict(depth_profile),
            "representative_ast": _pick_representative_ast(method, class_id, members, pattern_by_id),
        }
        records.append(rec)

    # Sort by size desc for downstream convenience
    records.sort(key=lambda r: (-r["size"], r["class_id"]))
    out = output_dir / f"classes_A{level}_{method}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    logger.info("  wrote %s (%d classes)", out, len(records))


# ---------------------------------------------------------------------------
# trajectory の構築
# ---------------------------------------------------------------------------


def build_trajectory(
    classes_by_level: dict[int, dict[str, list[str]]],
    cutout_ids: list[str],
    mb_depth_lookup: dict[str, tuple[int, str]],
) -> list[dict]:
    """Build per-cutout trajectory across abstraction levels.

    Args:
        classes_by_level: {level: {class_id: members}}.
        cutout_ids: cutout_ids observed at any level.
        mb_depth_lookup: cutout_id → (mb_id, depth).

    Returns:
        List of trajectory records, sorted by (mb_id, depth).
    """
    # Build reverse index: (level, cutout_id) -> class_id
    reverse: dict[int, dict[str, str]] = {}
    for L, classes in classes_by_level.items():
        rmap: dict[str, str] = {}
        for cid, members in classes.items():
            for m in members:
                rmap[m] = cid
        reverse[L] = rmap

    records: list[dict] = []
    for cid in sorted(cutout_ids):
        if cid not in mb_depth_lookup:
            continue
        mb, depth = mb_depth_lookup[cid]
        traj = {str(L): reverse.get(L, {}).get(cid, "") for L in LEVELS}
        records.append(
            {
                "cutout_id": cid,
                "mb_id": mb,
                "depth": depth,
                "trajectory": traj,
            }
        )
    return records


def save_trajectory(records: list[dict], method: str, output_dir: Path) -> None:
    out = output_dir / f"trajectory_{method}.json"
    with out.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    logger.info("  wrote %s (%d cutouts)", out, len(records))


# ---------------------------------------------------------------------------
# Monotonicity check (clusters at higher level should refine those at lower)
# ---------------------------------------------------------------------------


def check_monotonicity(
    classes_by_level: dict[int, dict[str, list[str]]],
) -> int:
    """Count mb pairs whose membership changes non-monotonically.

    Two cutouts that are in the SAME class at level L should also be in the
    same class at level L+1 (抽象度を上げると粒度は粗くなるのみ)．
    Returns the number of violating pairs across all level transitions.
    """
    violations = 0
    sorted_levels = sorted(classes_by_level.keys())
    for i in range(len(sorted_levels) - 1):
        L0 = sorted_levels[i]
        L1 = sorted_levels[i + 1]
        cls0 = classes_by_level[L0]
        cls1 = classes_by_level[L1]
        # Build cutout -> class for both
        r0 = {m: c for c, ms in cls0.items() for m in ms}
        r1 = {m: c for c, ms in cls1.items() for m in ms}
        # Iterate same-class pairs in L0
        for c, members in cls0.items():
            if len(members) < 2:
                continue
            base_c1 = r1.get(members[0])
            for m in members[1:]:
                if r1.get(m) != base_c1:
                    violations += 1
                    break  # count once per L0 class
    return violations
