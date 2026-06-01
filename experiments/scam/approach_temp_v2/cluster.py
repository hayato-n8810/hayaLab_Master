"""Common clustering utilities for approach_temp_v2.

approach_temp/cluster.py と同等の Union-Find / class_id 生成 / tree 再構築．
"""

from __future__ import annotations

import hashlib
import logging

from ast_node import TemplateNode, TreeNode

logger = logging.getLogger(__name__)


class UnionFind:
    """Union-Find with path compression and union-by-rank on string IDs."""

    def __init__(self, elements: list[str]) -> None:
        self._parent: dict[str, str] = {e: e for e in elements}
        self._rank: dict[str, int] = {e: 0 for e in elements}

    def add(self, x: str) -> None:
        """Add a new element if missing (idempotent)."""
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: str) -> str:
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def components(self) -> dict[str, list[str]]:
        """Return {root: sorted members} with deterministic ordering."""
        groups: dict[str, list[str]] = {}
        for e in self._parent:
            root = self.find(e)
            groups.setdefault(root, []).append(e)
        return {root: sorted(members) for root, members in sorted(groups.items())}


def build_classes(
    pairs: list[tuple[str, str]],
    all_ids: list[str],
) -> dict[str, list[str]]:
    """Build equivalence classes from pairwise merges."""
    uf = UnionFind(all_ids)
    for a, b in pairs:
        uf.union(a, b)
    return uf.components()


def _content_hash(value: str) -> str:
    """First 8 hex chars of SHA-256."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def make_class_id(level: int, method: str, hash_prefix: str) -> str:
    """``L{level}_{method}_{hash_prefix}`` class ID format."""
    return f"L{level}_{method}_{hash_prefix}"


def make_class_id_from_content(level: int, method: str, content: str) -> str:
    """Class ID derived from arbitrary content string."""
    return make_class_id(level, method, _content_hash(content))


def nodes_to_tree(nodes: list[TemplateNode]) -> TreeNode:
    """Reconstruct ordered tree from TemplateNode list using parent_relative."""
    if not nodes:
        return TreeNode(name="__empty__", value=None)

    index_to_tn: dict[int, TreeNode] = {}
    for tn in nodes:
        index_to_tn[tn.origin_index] = TreeNode(
            name=tn.name,
            value=tn.value,
            variadic=tn.variadic,
        )
    present: set[int] = set(index_to_tn.keys())
    roots: list[TreeNode] = []
    for tn in nodes:
        tree_node = index_to_tn[tn.origin_index]
        if tn.parent_relative and tn.parent_relative[-1] in present:
            index_to_tn[tn.parent_relative[-1]].children.append(tree_node)
        else:
            roots.append(tree_node)

    if len(roots) == 1:
        return roots[0]
    synthetic = TreeNode(name="__root__", value=None, variadic=True)
    synthetic.children = roots
    return synthetic
