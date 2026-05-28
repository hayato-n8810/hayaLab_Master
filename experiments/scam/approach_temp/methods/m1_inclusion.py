"""M1: One-directional tree inclusion clustering.

A pattern P is "included in" T (P ⊑ T) if P's tree can be embedded into T's tree
as an ordered subsequence of children at each level.

Complexity: O(N² × n²) where N = number of patterns, n = nodes per pattern.
"""

from __future__ import annotations

import logging

from ast_node import Pattern, TreeNode
from cluster import build_classes, make_class_id_from_content, nodes_to_tree

logger = logging.getLogger(__name__)


def node_matches(p: TreeNode, t: TreeNode) -> bool:
    """Check if pattern node p matches target node t.

    Match conditions:
    - name must match exactly.
    - value: if p.value is None (abstracted/wildcard), it matches any t.value.
      If p.value is set, it must equal t.value exactly.

    Args:
        p: pattern node.
        t: target node.

    Returns:
        True if p matches t.
    """
    if p.name != t.name:
        return False
    if p.value is None:
        return True  # wildcard
    return p.value == t.value


def ordered_subsequence_match(ps: list[TreeNode], ts: list[TreeNode]) -> bool:
    """Check if ps can be embedded into ts as an ordered subsequence.

    Uses DP to find if all nodes in ps (the pattern children) can be matched
    to a subsequence of ts (the target children) in order.

    Variadic pattern children can skip any number of target children (they
    act as ".*" in the sequence). Non-variadic pattern children must match
    exactly one target child at the current position (but may skip target
    children before it).

    Args:
        ps: pattern children list.
        ts: target children list.

    Returns:
        True if ps is an ordered embedded subsequence of ts (with tree inclusion
        recursion for each matched pair).
    """
    # dp[i][j] = can we match ps[:i] using ts[:j]?
    m, n = len(ps), len(ts)
    dp = [[False] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = True

    # Base: 0 pattern children match any prefix of ts (0 target children consumed)
    for j in range(n + 1):
        dp[0][j] = True

    for i in range(1, m + 1):
        p_child = ps[i - 1]
        for j in range(1, n + 1):
            t_child = ts[j - 1]
            # Option 1: skip t_child (t_child not used for p_child)
            dp[i][j] = dp[i][j - 1] and False  # must still match p_child somehow

            # Actually: dp[i][j] = dp[i][j-1] OR (dp[i-1][j-1] and includes(p_child, t_child))
            # dp[i][j-1] means we skip t_child for matching p_child (look at ts[:j-1])
            skip = dp[i][j - 1]
            match = dp[i - 1][j - 1] and includes(p_child, t_child)
            dp[i][j] = skip or match

    return dp[m][n]


def includes(p: TreeNode, t: TreeNode) -> bool:
    """Check if pattern tree P is included in target tree T (P ⊑ T).

    P ⊑ T means P's structure can be found anywhere inside T, with P's
    children embedded as an ordered subsequence of T's children at each level.

    Args:
        p: pattern root TreeNode.
        t: target root TreeNode.

    Returns:
        True if P ⊑ T.
    """
    if node_matches(p, t):
        if ordered_subsequence_match(p.children, t.children):
            return True
    # Try embedding P into any child of T
    return any(includes(p, child) for child in t.children)


def cluster_m1(patterns: list[Pattern]) -> dict[str, list[str]]:
    """Cluster patterns using one-directional tree inclusion.

    For each pair (A, B), if A ⊑ B or B ⊑ A, they are merged into the same class.
    Uses Union-Find to accumulate transitive merges.

    Args:
        patterns: list of Pattern objects at the same abstraction level.

    Returns:
        Dict mapping class_id → sorted list of cutout_ids.
    """
    if not patterns:
        return {}

    level = patterns[0].abst_level
    all_ids = [p.cutout_id for p in patterns]

    # Build tree for each pattern
    trees: dict[str, TreeNode] = {p.cutout_id: nodes_to_tree(p.ast_template) for p in patterns}

    # Find all inclusion pairs
    pairs: list[tuple[str, str]] = []
    n = len(patterns)
    for i in range(n):
        for j in range(i + 1, n):
            a = patterns[i]
            b = patterns[j]
            ta, tb = trees[a.cutout_id], trees[b.cutout_id]
            if includes(ta, tb) or includes(tb, ta):
                pairs.append((a.cutout_id, b.cutout_id))

    classes = build_classes(pairs, all_ids)

    # Rename class IDs to stable format
    result: dict[str, list[str]] = {}
    for root_id, members in classes.items():
        class_id = make_class_id_from_content(level, "M1", ",".join(sorted(members)))
        result[class_id] = members

    logger.debug(
        "M1 clustering at level %d: %d patterns → %d classes, %d inclusion pairs",
        level,
        len(patterns),
        len(result),
        len(pairs),
    )
    return result
