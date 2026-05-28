"""dataclass definitions for Slow Pattern Clustering pipeline.

Defines the core types used throughout the pipeline:
- NodePayload: raw node from 01_cutouts.json
- Cutout: normalized cutout keyed by (mb_id, depth)
- TemplateNode: abstracted node (post-abstract.py processing)
- Pattern: abstracted representation of a cutout at a given level
- TreeNode: tree structure for M1-M3 methods
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodePayload:
    """Raw AST node payload from 01_cutouts.json.

    Attributes:
        origin_index: unique index of the node in the original AST.
        begin: start position in source.
        end: end position in source.
        label: human-readable label "name: value [begin,end]".
        name: node kind (e.g. "identifier", "call_expression").
        value: node value (e.g. "VAR_2", "filter", "(", "function_like").
        parent: ancestor path (list of origin_index from root to direct parent).
    """

    origin_index: int
    begin: int
    end: int
    label: str
    name: str
    value: str
    parent: list[int]

    @classmethod
    def from_dict(cls, d: dict) -> "NodePayload":
        """Construct from a raw JSON dict."""
        return cls(
            origin_index=d["origin_index"],
            begin=d["begin"],
            end=d["end"],
            label=d["label"],
            name=d["name"],
            value=d["value"],
            parent=d["parent"],
        )


@dataclass
class Cutout:
    """Normalized cutout keyed by (mb_id, depth).

    Attributes:
        mb_id: microbenchmark id (from top-level "id" field).
        depth: cutout type ("Diff", "Brother", "ExParent", "Parent").
        diff_node_indices: list of origin_index values that are diff nodes.
        nodes: list of NodePayload in this cutout.
    """

    mb_id: int
    depth: str  # "Diff" / "Brother" / "ExParent" / "Parent"
    diff_node_indices: list[int]
    nodes: list[NodePayload]

    @property
    def cutout_id(self) -> str:
        """Unique identifier for this cutout: "{mb_id}_{depth}"."""
        return f"{self.mb_id}_{self.depth}"


@dataclass
class TemplateNode:
    """Abstracted AST node after applying abstraction rules.

    Attributes:
        origin_index: original node index in the AST.
        name: node kind (always kept).
        value: node value, may be replaced by "VAR", "LITERAL", "FUNC", etc.,
            or None if fully abstracted.
        parent_relative: list of origin_index for ancestors in this cutout.
        slot_id: slot identifier for VAR_ / LITERAL_ / etc. slots (or None).
        is_terminal: True if this is a leaf node (no children in cutout).
        variadic: True if this node's children may vary in count (for M1-M3).
    """

    origin_index: int
    name: str
    value: str | None
    parent_relative: list[int]
    slot_id: str | None = None
    is_terminal: bool = False
    variadic: bool = False

    def to_dict(self) -> dict:
        """Serialize to a plain dict (for JSON output)."""
        return {
            "origin_index": self.origin_index,
            "name": self.name,
            "value": self.value,
            "parent_relative": self.parent_relative,
            "slot_id": self.slot_id,
            "is_terminal": self.is_terminal,
            "variadic": self.variadic,
        }


@dataclass
class Pattern:
    """Abstracted representation of a cutout at a given abstraction level.

    Attributes:
        mb_id: microbenchmark id.
        depth: cutout type.
        abst_level: abstraction level (0-5).
        ast_template: list of TemplateNode (punctuation excluded).
    """

    mb_id: int
    depth: str
    abst_level: int
    ast_template: list[TemplateNode]

    @property
    def cutout_id(self) -> str:
        """Unique identifier: "{mb_id}_{depth}"."""
        return f"{self.mb_id}_{self.depth}"


@dataclass
class TreeNode:
    """Tree structure node for M1-M3 inclusion / anti-unification methods.

    Attributes:
        name: node kind.
        value: node value, or None if abstracted (wildcard in matching).
        children: ordered list of child TreeNode objects.
        variadic: if True, children may vary in count (enables partial matching).
        is_slot: True if this node is a slot / wildcard (from LGG).
    """

    name: str
    value: str | None
    children: list["TreeNode"] = field(default_factory=list)
    variadic: bool = False
    is_slot: bool = False

    def size(self) -> int:
        """Total number of nodes in the subtree rooted at this node."""
        return 1 + sum(c.size() for c in self.children)

    def non_slot_size(self) -> int:
        """Number of non-slot nodes in the subtree."""
        count = 0 if self.is_slot else 1
        return count + sum(c.non_slot_size() for c in self.children)
