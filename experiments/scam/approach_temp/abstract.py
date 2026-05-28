"""Abstraction rules for A0..A5 levels.

Applies progressive abstraction to AST nodes, producing TemplateNode objects.
Level 0 is the most concrete (values preserved), level 5 is the most abstract
(almost all values replaced by wildcards/slots).

Abstraction levels:
    A0: no abstraction — all names and values kept as-is.
    A1: variable identifiers (VAR_*) replaced by slot IDs.
    A2: literal values (LITERAL_*) replaced by slot IDs; VAR_* by slots.
    A3: function-like names unified to a single token "function_like".
    A4: built-in identifiers kept, other identifiers abstracted.
    A5: all identifier values abstracted (name only).
"""

from __future__ import annotations

import logging
from typing import Optional

from ast_node import Cutout, NodePayload, Pattern, TemplateNode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constant sets
# ---------------------------------------------------------------------------

PUNCTUATION_NAMES: frozenset[str] = frozenset(["(", ")", ",", ".", ";", "{", "}", "[", "]", ":", '"', "'", "_"])

PUNCTUATION_VALUES: frozenset[str] = frozenset(["(", ")", ",", ".", ";", "{", "}", "[", "]", ":", '"', "'", "_"])

FUNCTION_LIKE_NAMES: frozenset[str] = frozenset(
    [
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "generator_function",
        "generator_function_declaration",
        "function",
    ]
)

BUILTIN_IDENTIFIERS: frozenset[str] = frozenset(
    [
        "Object",
        "Array",
        "Math",
        "String",
        "Number",
        "Boolean",
        "JSON",
        "Promise",
        "Map",
        "Set",
        "WeakMap",
        "WeakSet",
        "Symbol",
        "RegExp",
        "Date",
        "Error",
        "Function",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "toString",
        "valueOf",
        "hasOwnProperty",
        "prototype",
        "constructor",
        "length",
        "push",
        "pop",
        "shift",
        "unshift",
        "slice",
        "splice",
        "indexOf",
        "forEach",
        "map",
        "filter",
        "reduce",
        "find",
        "some",
        "every",
        "keys",
        "values",
        "entries",
        "assign",
        "create",
        "freeze",
        "keys",
        "undefined",
        "null",
        "true",
        "false",
        "NaN",
        "Infinity",
        "console",
        "log",
        "warn",
        "error",
    ]
)

# Abstraction-prefix markers in values
VAR_PREFIX = "VAR_"
LITERAL_PREFIX = "LITERAL_"
FUNC_PREFIX = "FUNC_"

# Token used for unified function-like names at A3+
FUNCTION_LIKE_TOKEN = "function_like"


def _is_punctuation(node: NodePayload) -> bool:
    """Return True if the node is a punctuation token to be excluded."""
    return node.name.strip() in PUNCTUATION_NAMES or node.value.strip() in PUNCTUATION_VALUES


def _is_var_node(node: NodePayload) -> bool:
    """Return True if the node value represents a variable placeholder."""
    return node.value.startswith(VAR_PREFIX)


def _is_literal_node(node: NodePayload) -> bool:
    """Return True if the node value represents a literal placeholder."""
    return node.value.startswith(LITERAL_PREFIX)


def _is_func_node(node: NodePayload) -> bool:
    """Return True if the node value represents a function placeholder."""
    return node.value.startswith(FUNC_PREFIX)


def _is_function_like(node: NodePayload) -> bool:
    """Return True if the node name is a function-like construct."""
    return node.name in FUNCTION_LIKE_NAMES


def abstract_node(
    node: NodePayload,
    level: int,
    slot_map: Optional[dict[str, str]] = None,
) -> Optional[TemplateNode]:
    """Apply abstraction rules for the given level to a single node.

    Punctuation nodes are always excluded (return None).

    Args:
        node: the raw NodePayload to abstract.
        level: abstraction level (0-5).
        slot_map: mutable dict mapping original VAR_/LITERAL_ values to slot IDs.
            Used to ensure consistent slot numbering across a single cutout.
            Pass the same dict for all nodes in a cutout.

    Returns:
        A TemplateNode, or None if the node should be excluded (punctuation).
    """
    if slot_map is None:
        slot_map = {}

    if _is_punctuation(node):
        return None

    name = node.name
    value: str | None = node.value
    slot_id: str | None = None
    variadic = False

    # --- A0: keep everything as-is ---
    if level == 0:
        pass

    # --- A1: replace VAR_* with slot IDs ---
    elif level == 1:
        if _is_var_node(node):
            if value not in slot_map:
                slot_map[value] = f"$v{len([k for k in slot_map if k.startswith(VAR_PREFIX)])}"
            slot_id = slot_map[value]
            value = slot_id

    # --- A2: replace VAR_* and LITERAL_* with slot IDs ---
    elif level == 2:
        if _is_var_node(node):
            if value not in slot_map:
                slot_map[value] = f"$v{len([k for k in slot_map if k.startswith(VAR_PREFIX)])}"
            slot_id = slot_map[value]
            value = slot_id
        elif _is_literal_node(node):
            if value not in slot_map:
                slot_map[value] = f"$l{len([k for k in slot_map if k.startswith(LITERAL_PREFIX)])}"
            slot_id = slot_map[value]
            value = slot_id

    # --- A3: + unify function-like names ---
    elif level == 3:
        if _is_var_node(node):
            if value not in slot_map:
                slot_map[value] = f"$v{len([k for k in slot_map if k.startswith(VAR_PREFIX)])}"
            slot_id = slot_map[value]
            value = slot_id
        elif _is_literal_node(node):
            if value not in slot_map:
                slot_map[value] = f"$l{len([k for k in slot_map if k.startswith(LITERAL_PREFIX)])}"
            slot_id = slot_map[value]
            value = slot_id
        if _is_function_like(node):
            name = FUNCTION_LIKE_TOKEN
            variadic = True

    # --- A4: + abstract non-builtin identifiers; keep builtins ---
    elif level == 4:
        if _is_var_node(node):
            slot_id = "$var"
            value = "$var"
        elif _is_literal_node(node):
            slot_id = "$lit"
            value = "$lit"
        elif _is_func_node(node):
            slot_id = "$func"
            value = "$func"
        elif node.value not in BUILTIN_IDENTIFIERS:
            value = None  # abstract non-builtin identifiers
        if _is_function_like(node):
            name = FUNCTION_LIKE_TOKEN
            variadic = True

    # --- A5: abstract all identifier values ---
    elif level == 5:
        value = None  # fully abstract all values
        if _is_function_like(node):
            name = FUNCTION_LIKE_TOKEN
            variadic = True

    return TemplateNode(
        origin_index=node.origin_index,
        name=name,
        value=value,
        parent_relative=list(node.parent),
        slot_id=slot_id,
        is_terminal=False,  # will be set in abstract_cutout
        variadic=variadic,
    )


def abstract_cutout(cutout: Cutout, level: int) -> Pattern:
    """Apply abstraction rules to all nodes in a cutout.

    Punctuation nodes are excluded. The remaining TemplateNodes are returned
    in the order they appear in the cutout's nodes list.

    Also marks is_terminal for nodes that have no children within the cutout
    (i.e., their origin_index does not appear as parent[-1] of any other node).

    Args:
        cutout: the Cutout to abstract.
        level: abstraction level (0-5).

    Returns:
        A Pattern with the abstracted AST template.
    """
    slot_map: dict[str, str] = {}
    template_nodes: list[TemplateNode] = []

    for node in cutout.nodes:
        tnode = abstract_node(node, level, slot_map)
        if tnode is not None:
            template_nodes.append(tnode)

    # Determine terminal nodes: nodes whose origin_index is not anyone's parent
    parent_indices: set[int] = set()
    for node in cutout.nodes:
        if node.parent:
            parent_indices.add(node.parent[-1])

    for tnode in template_nodes:
        tnode.is_terminal = tnode.origin_index not in parent_indices

    return Pattern(
        mb_id=cutout.mb_id,
        depth=cutout.depth,
        abst_level=level,
        ast_template=template_nodes,
    )
