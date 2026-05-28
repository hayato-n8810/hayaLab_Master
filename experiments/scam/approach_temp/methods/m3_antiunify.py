"""M3: Anti-unification (LGG) clustering.

Uses Least General Generalization (LGG) to measure structural similarity between
pattern trees and performs greedy merging under configurable thresholds.

Complexity: O(N² × n) for similarity computation.
"""

from __future__ import annotations

import itertools
import logging

from ast_node import Pattern, TreeNode
from cluster import make_class_id_from_content, nodes_to_tree

logger = logging.getLogger(__name__)

# Slot node sentinel name
SLOT_NAME = "__slot__"


def _slot_node() -> TreeNode:
    """Create a wildcard/slot TreeNode."""
    return TreeNode(name=SLOT_NAME, value=None, is_slot=True)


def _lcs_pairs(a_children: list[TreeNode], b_children: list[TreeNode]) -> list[tuple[int, int]]:
    """Compute LCS index pairs for two child lists using DP.

    Returns list of (i, j) pairs where a_children[i] and b_children[j] are matched.
    Matching prefers nodes with the same name (LGG makes most sense when names match).
    """
    m, n = len(a_children), len(b_children)
    # DP table: dp[i][j] = length of LCS of a_children[:i] and b_children[:j]
    # where LCS is defined as matching pairs with same name
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a_children[i - 1].name == b_children[j - 1].name:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    # Backtrack
    pairs: list[tuple[int, int]] = []
    i, j = m, n
    while i > 0 and j > 0:
        if a_children[i - 1].name == b_children[j - 1].name and dp[i][j] == dp[i - 1][j - 1] + 1:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def lgg(a: TreeNode, b: TreeNode) -> TreeNode:
    """Compute the Least General Generalization of trees A and B.

    Rules:
    - If names differ: return a slot node.
    - If names match: recursively lgg children using LCS alignment.
      Unmatched children become slot nodes.
    - value: if both values are equal (and non-None), keep; else None (wildcard).

    Args:
        a: first tree.
        b: second tree.

    Returns:
        LGG tree.
    """
    if a.name != b.name:
        return _slot_node()

    # Names match
    merged_value: str | None
    if a.value is None or b.value is None:
        merged_value = None
    elif a.value == b.value:
        merged_value = a.value
    else:
        merged_value = None

    # Merge children via LCS alignment
    merged_children: list[TreeNode] = []

    if not a.children and not b.children:
        pass  # leaf node
    elif not a.children or not b.children:
        # One side has children, other doesn't → slot for each child
        max_children = max(len(a.children), len(b.children))
        merged_children = [_slot_node() for _ in range(max_children)]
    else:
        # Both have children: LCS matching
        pairs = _lcs_pairs(a.children, b.children)

        # Reconstruct children in order: walk a.children, for each either
        # slot (unmatched) or lgg with matched b child; unmatched b after
        b_unmatched_before: list[list[int]] = [[] for _ in range(len(a.children) + 1)]
        # place unmatched b before their nearest matched or at end
        used_b: set[int] = {j for _, j in pairs}
        prev_bi = -1
        for ai, bi in pairs:
            # b indices between prev_bi+1 and bi-1 are unmatched before a[ai]
            for bj in range(prev_bi + 1, bi):
                if bj not in used_b:
                    b_unmatched_before[ai].append(bj)
            prev_bi = bi
        # remaining unmatched b after last a match
        last_bi = pairs[-1][1] if pairs else -1
        trailing_b = [bj for bj in range(last_bi + 1, len(b.children)) if bj not in used_b]

        pair_map = dict(pairs)
        for ai, a_child in enumerate(a.children):
            # Insert slot for each unmatched b before this a
            for bj in b_unmatched_before[ai]:
                merged_children.append(_slot_node())
            if ai in pair_map:
                bj = pair_map[ai]
                merged_children.append(lgg(a_child, b.children[bj]))
            else:
                merged_children.append(_slot_node())
        # Trailing unmatched b
        for _ in trailing_b:
            merged_children.append(_slot_node())

    result = TreeNode(
        name=a.name,
        value=merged_value,
        children=merged_children,
        variadic=a.variadic or b.variadic,
    )
    return result


def sim(a: TreeNode, b: TreeNode) -> float:
    """Compute Jaccard-style similarity between two trees via LGG.

    sim(A, B) = |non_slot(lgg(A, B))| / (|A| + |B| - |lgg(A, B)|)

    Args:
        a: first tree.
        b: second tree.

    Returns:
        Similarity in [0, 1].
    """
    lgg_tree = lgg(a, b)
    lgg_size = lgg_tree.size()
    non_slot = lgg_tree.non_slot_size()
    denom = a.size() + b.size() - lgg_size
    if denom <= 0:
        return 1.0
    return non_slot / denom


def is_degenerate(lgg_tree: TreeNode, initial_size: int, rho: float) -> bool:
    """Check if the LGG has degenerated (too many slots).

    A degeneration occurs when non_slot(lgg) < rho * initial_size.

    Args:
        lgg_tree: the current LGG tree.
        initial_size: size of the initial (seed) tree before merging.
        rho: minimum non-slot ratio threshold.

    Returns:
        True if the LGG is degenerate.
    """
    if initial_size == 0:
        return False
    return lgg_tree.non_slot_size() < rho * initial_size


def cluster_m3(
    patterns: list[Pattern],
    tau_sim: float = 0.5,
    kappa: float = 3.0,
    rho: float = 0.5,
) -> dict[str, list[str]]:
    """Cluster patterns using greedy anti-unification (LGG).

    Algorithm:
    1. Compute pairwise similarity scores.
    2. Filter pairs by tau_sim and size ratio kappa.
    3. Sort pairs by similarity descending.
    4. Greedily merge pairs using Union-Find, checking non-degeneracy.

    Args:
        patterns: list of Pattern objects at the same abstraction level.
        tau_sim: minimum similarity threshold for merging.
        kappa: maximum size ratio (max/min) for merging.
        rho: minimum non-slot ratio to prevent degeneracy.

    Returns:
        Dict mapping class_id → sorted list of cutout_ids.
    """
    if not patterns:
        return {}

    level = patterns[0].abst_level
    all_ids = [p.cutout_id for p in patterns]

    # Build trees once
    trees: dict[str, TreeNode] = {p.cutout_id: nodes_to_tree(p.ast_template) for p in patterns}
    sizes: dict[str, int] = {cid: t.size() for cid, t in trees.items()}

    # Compute pairwise similarities
    candidates: list[tuple[float, str, str]] = []
    ids = all_ids
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a_id, b_id = ids[i], ids[j]
            sa, sb = sizes[a_id], sizes[b_id]
            # Size ratio filter
            if sa == 0 or sb == 0:
                continue
            ratio = max(sa, sb) / min(sa, sb)
            if ratio > kappa:
                continue
            s = sim(trees[a_id], trees[b_id])
            if s >= tau_sim:
                candidates.append((s, a_id, b_id))

    # Sort by similarity descending
    candidates.sort(key=lambda x: -x[0])

    # Union-Find for greedy merging
    from cluster import UnionFind

    uf = UnionFind(all_ids)
    # Track current LGG and initial size for each component (root → lgg_tree)
    component_lgg: dict[str, TreeNode] = {cid: trees[cid] for cid in all_ids}
    component_initial_size: dict[str, int] = {cid: sizes[cid] for cid in all_ids}

    pairs: list[tuple[str, str]] = []
    for _, a_id, b_id in candidates:
        ra, rb = uf.find(a_id), uf.find(b_id)
        if ra == rb:
            continue
        # Compute merged LGG
        merged = lgg(component_lgg[ra], component_lgg[rb])
        init_size = component_initial_size[ra]
        if is_degenerate(merged, init_size, rho):
            continue
        # Merge
        uf.union(a_id, b_id)
        new_root = uf.find(a_id)
        component_lgg[new_root] = merged
        component_initial_size[new_root] = init_size
        pairs.append((a_id, b_id))

    classes = uf.components()
    result: dict[str, list[str]] = {}
    for _root, members in sorted(classes.items(), key=lambda x: sorted(x[1])):
        members_sorted = sorted(members)
        class_id = make_class_id_from_content(level, "M3", ",".join(members_sorted))
        result[class_id] = members_sorted

    logger.debug(
        "M3 clustering (tau=%.1f, kappa=%.1f, rho=%.1f) at level %d: %d patterns → %d classes, %d merges",
        tau_sim,
        kappa,
        rho,
        level,
        len(patterns),
        len(result),
        len(pairs),
    )
    return result


def grid_search_m3(
    patterns: list[Pattern],
) -> dict[tuple[float, float, float], dict[str, list[str]]]:
    """Run grid search over M3 hyperparameters.

    Grid:
        tau_sim ∈ {0.3, 0.4, 0.5, 0.6, 0.7}
        kappa   ∈ {2, 3, 5}
        rho     ∈ {0.3, 0.5}

    Args:
        patterns: list of Pattern objects.

    Returns:
        Dict mapping (tau_sim, kappa, rho) → clustering result dict.
    """
    tau_values = [0.3, 0.4, 0.5, 0.6, 0.7]
    kappa_values = [2.0, 3.0, 5.0]
    rho_values = [0.3, 0.5]

    results: dict[tuple[float, float, float], dict[str, list[str]]] = {}
    for tau, kappa, rho in itertools.product(tau_values, kappa_values, rho_values):
        key = (tau, kappa, rho)
        results[key] = cluster_m3(patterns, tau_sim=tau, kappa=kappa, rho=rho)
        logger.info(
            "Grid M3 (tau=%.1f, kappa=%.1f, rho=%.1f): %d classes",
            tau,
            kappa,
            rho,
            len(results[key]),
        )

    return results
