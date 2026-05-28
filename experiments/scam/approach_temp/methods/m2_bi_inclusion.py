"""M2: Bi-directional tree inclusion clustering via hit sets.

Two patterns P1 and P2 are in the same class iff their hit sets are identical.
hit_set(P) = { cutout_id T : P ⊑ T } — the set of all targets that P is included in.

This is stricter than M1 (class count >= M1 classes) because two patterns must
"include into" exactly the same set of targets to be considered equivalent.

Complexity: O(N² × n²) for hit set computation + O(N) for grouping.
"""

from __future__ import annotations

import logging

from ast_node import Pattern, TreeNode
from cluster import make_class_id_from_content, nodes_to_tree

from methods.m1_inclusion import includes

logger = logging.getLogger(__name__)


def compute_hit_sets(patterns: list[Pattern]) -> dict[str, frozenset[str]]:
    """Compute the hit set for each pattern.

    hit_set(P) = { cutout_id(T) : P ⊑ T } for all T in patterns.

    Args:
        patterns: list of Pattern objects at the same abstraction level.

    Returns:
        Dict mapping cutout_id → frozenset of cutout_ids that this pattern
        is included in.
    """
    # Build trees once
    trees: dict[str, TreeNode] = {p.cutout_id: nodes_to_tree(p.ast_template) for p in patterns}

    hit_sets: dict[str, frozenset[str]] = {}
    for p in patterns:
        tp = trees[p.cutout_id]
        hits: set[str] = set()
        for t in patterns:
            tt = trees[t.cutout_id]
            if includes(tp, tt):
                hits.add(t.cutout_id)
        hit_sets[p.cutout_id] = frozenset(hits)

    return hit_sets


def cluster_m2(patterns: list[Pattern]) -> dict[str, list[str]]:
    """Cluster patterns using bi-directional hit-set equality.

    Two patterns are in the same class iff their hit sets are identical.

    Args:
        patterns: list of Pattern objects at the same abstraction level.

    Returns:
        Dict mapping class_id → sorted list of cutout_ids.
    """
    if not patterns:
        return {}

    level = patterns[0].abst_level
    hit_sets = compute_hit_sets(patterns)

    # Group by hit_set
    set_to_ids: dict[frozenset[str], list[str]] = {}
    for cid, hs in hit_sets.items():
        set_to_ids.setdefault(hs, []).append(cid)

    result: dict[str, list[str]] = {}
    for hs, ids in sorted(set_to_ids.items(), key=lambda x: sorted(x[1])):
        members = sorted(ids)
        class_id = make_class_id_from_content(level, "M2", ",".join(sorted(hs)) + "|" + ",".join(members))
        result[class_id] = members

    logger.debug(
        "M2 clustering at level %d: %d patterns → %d classes",
        level,
        len(patterns),
        len(result),
    )
    return result
