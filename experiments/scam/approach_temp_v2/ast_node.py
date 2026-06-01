"""dataclass definitions for approach_temp_v2.

approach_temp/ast_node.py と互換のデータモデル．`docs/aggregate.md` の
M0/M1/M2 集約手法では木構造表現を必要としない場合があるため、
TreeNode は LGG 系手法 (M3) でのみ使用する．
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodePayload:
    """Raw AST node payload.

    Attributes:
        origin_index: original node index in the source AST.
        begin: start position in source code.
        end: end position in source code.
        label: human-readable label.
        name: node kind (e.g. "identifier", "call_expression").
        value: node value (e.g. "VAR_2", "filter").
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
        """Construct from raw JSON dict."""
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
class TemplateNode:
    """Abstracted AST node (post-abstraction.py).

    Attributes:
        origin_index: original node index.
        name: node kind (preserved).
        value: node value (may be slot ID such as ``$v0``).
        parent_relative: list of origin_index for ancestors in this cutout.
        slot_id: slot identifier (or None).
        is_terminal: True if this is a leaf inside the cutout.
        variadic: True if children may vary (e.g. function_like).
    """

    origin_index: int
    name: str
    value: str | None
    parent_relative: list[int]
    slot_id: str | None = None
    is_terminal: bool = False
    variadic: bool = False

    def to_dict(self) -> dict:
        return {
            "origin_index": self.origin_index,
            "name": self.name,
            "value": self.value,
            "parent_relative": self.parent_relative,
            "slot_id": self.slot_id,
            "is_terminal": self.is_terminal,
            "variadic": self.variadic,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TemplateNode":
        return cls(
            origin_index=d["origin_index"],
            name=d["name"],
            value=d.get("value"),
            parent_relative=d.get("parent_relative") or d.get("parent") or [],
            slot_id=d.get("slot_id"),
            is_terminal=d.get("is_terminal", False),
            variadic=d.get("variadic", False),
        )


@dataclass
class Pattern:
    """Abstracted representation of a cutout at a given level.

    Attributes:
        mb_id: microbenchmark id.
        depth: cutout type ("Diff" / "Brother" / "ExParent" / "Parent").
        abst_level: abstraction level (0-3).
        ast_template: list of TemplateNode (punctuation excluded).
        diff_node_indices: optional, original diff node origin_index list.
    """

    mb_id: int
    depth: str
    abst_level: int
    ast_template: list[TemplateNode]
    diff_node_indices: list[int] = field(default_factory=list)

    @property
    def cutout_id(self) -> str:
        return f"{self.mb_id}_{self.depth}"


@dataclass
class TreeNode:
    """Ordered tree node for LGG / TED computation."""

    name: str
    value: str | None
    children: list["TreeNode"] = field(default_factory=list)
    variadic: bool = False
    is_slot: bool = False

    def size(self) -> int:
        return 1 + sum(c.size() for c in self.children)

    def non_slot_size(self) -> int:
        count = 0 if self.is_slot else 1
        return count + sum(c.non_slot_size() for c in self.children)
