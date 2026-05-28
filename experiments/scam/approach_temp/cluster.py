"""Common clustering utilities: Union-Find, class building, and tree construction.

Provides:
- UnionFind: path-compression + union-by-rank.
- build_classes: build class dict from (id, id) pairs using Union-Find.
- make_class_id: generate stable class IDs.
- nodes_to_tree: reconstruct tree structure from TemplateNode list.
"""

from __future__ import annotations

import hashlib
import logging

from ast_node import TemplateNode, TreeNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------


class UnionFind:
    """Union-Find with path compression and union-by-rank.

    Operates on string IDs.
    """

    def __init__(self, elements: list[str]) -> None:
        self._parent: dict[str, str] = {e: e for e in elements}
        self._rank: dict[str, int] = {e: 0 for e in elements}

    def find(self, x: str) -> str:
        """Find root of x with path compression."""
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: str, y: str) -> None:
        """Union the sets containing x and y."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def components(self) -> dict[str, list[str]]:
        """Return a dict mapping root → list of elements in that component."""
        groups: dict[str, list[str]] = {}
        for e in self._parent:
            root = self.find(e)
            groups.setdefault(root, []).append(e)
        return groups


# ---------------------------------------------------------------------------
# Class construction
# ---------------------------------------------------------------------------


def build_classes(
    pairs: list[tuple[str, str]],
    all_ids: list[str],
) -> dict[str, list[str]]:
    """Build equivalence classes using Union-Find.

    Args:
        pairs: list of (cutout_id_a, cutout_id_b) pairs to be merged.
        all_ids: all cutout IDs (ensures singletons are also included).

    Returns:
        Dict mapping class_id (root cutout_id) → sorted list of member cutout_ids.
    """
    uf = UnionFind(all_ids)
    for a, b in pairs:
        uf.union(a, b)
    components = uf.components()
    # Sort members for reproducibility
    return {root: sorted(members) for root, members in sorted(components.items())}


def make_class_id(level: int, method: str, hash_prefix: str) -> str:
    """Generate a stable class ID string.

    Format: L{level}_{method}_{hash_prefix}

    Args:
        level: abstraction level (0-5).
        method: method name (e.g. "M0", "M1").
        hash_prefix: first 8 chars of a hash uniquely identifying the class.

    Returns:
        Class ID string.
    """
    return f"L{level}_{method}_{hash_prefix}"


def _content_hash(value: str) -> str:
    """Return first 8 hex chars of SHA-256 of value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def make_class_id_from_content(level: int, method: str, content: str) -> str:
    """Generate a stable class ID from arbitrary content string.

    Args:
        level: abstraction level.
        method: method name.
        content: canonical string that uniquely identifies the class.

    Returns:
        Class ID string.
    """
    return make_class_id(level, method, _content_hash(content))


# ---------------------------------------------------------------------------
# Tree construction from TemplateNode list
# ---------------------------------------------------------------------------


def nodes_to_tree(nodes: list[TemplateNode]) -> TreeNode:
    """Reconstruct a tree structure from a flat list of TemplateNode objects.

    Uses the parent_relative field (ancestor path) to determine parent-child
    relationships. Nodes whose parent[-1] is not present in the cutout are
    treated as roots. If there are multiple roots, a synthetic root node is
    inserted.

    Args:
        nodes: list of TemplateNode from a Pattern.

    Returns:
        Root TreeNode of the reconstructed tree.
    """
    if not nodes:
        return TreeNode(name="__empty__", value=None)

    # Build a mapping from origin_index → TreeNode
    index_to_treenode: dict[int, TreeNode] = {}
    for tnode in nodes:
        index_to_treenode[tnode.origin_index] = TreeNode(
            name=tnode.name,
            value=tnode.value,
            variadic=tnode.variadic,
        )

    present_indices: set[int] = set(index_to_treenode.keys())

    roots: list[TreeNode] = []

    for tnode in nodes:
        tree_node = index_to_treenode[tnode.origin_index]
        parent_rel = tnode.parent_relative

        # Find direct parent: parent_rel[-1] if it is inside the cutout
        if parent_rel and parent_rel[-1] in present_indices:
            parent_node = index_to_treenode[parent_rel[-1]]
            parent_node.children.append(tree_node)
        else:
            roots.append(tree_node)

    if len(roots) == 1:
        return roots[0]

    # Multiple roots: wrap under a synthetic root
    synthetic = TreeNode(name="__root__", value=None, variadic=True)
    synthetic.children = roots
    return synthetic
