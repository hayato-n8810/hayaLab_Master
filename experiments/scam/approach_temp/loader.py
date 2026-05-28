"""Loader and filtering for 01_cutouts.json.

Loads the nested cutout JSON and normalizes it to a flat list of Cutout objects,
keyed by (mb_id, depth). Also provides filtering logic to remove content-free cutouts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ast_node import Cutout, NodePayload

logger = logging.getLogger(__name__)

# Depths present in the nested cutout format
DEPTHS = ("Diff", "Brother", "ExParent", "Parent")

# Punctuation names/values that constitute "punctuation-only" cutouts
PUNCTUATION_NAMES: frozenset[str] = frozenset(["(", ")", ",", ".", ";", "{", "}", "[", "]", ":", '"', "'", "_"])

# Abstraction prefix values that indicate content-free nodes
ABSTRACTION_PREFIXES: tuple[str, ...] = ("VAR_", "LITERAL_", "FUNC_", "ARG_", "SLOT_")


def load_cutouts(path: str | Path) -> list[Cutout]:
    """Load the nested 01_cutouts.json and return a flat list of Cutout objects.

    Each top-level entry in the JSON has an "id" field and a "cutouts" dict
    with keys "Diff", "Brother", "ExParent", "Parent". Each key maps to a dict
    with "diff_node_indices" and "nodes". This function expands all (mb_id, depth)
    combinations into individual Cutout objects.

    Args:
        path: path to 01_cutouts.json.

    Returns:
        Flat list of Cutout objects, one per (mb_id, depth) pair.
    """
    path = Path(path)
    logger.info("Loading cutouts from %s", path)

    with path.open(encoding="utf-8") as f:
        raw = json.load(f)

    cutouts: list[Cutout] = []
    for entry in raw:
        mb_id: int = entry["id"]
        for depth in DEPTHS:
            if depth not in entry.get("cutouts", {}):
                continue
            cutout_data = entry["cutouts"][depth]
            nodes = [NodePayload.from_dict(n) for n in cutout_data.get("nodes", [])]
            cutout = Cutout(
                mb_id=mb_id,
                depth=depth,
                diff_node_indices=cutout_data.get("diff_node_indices", []),
                nodes=nodes,
            )
            cutouts.append(cutout)

    logger.info("Loaded %d cutouts from %d entries", len(cutouts), len(raw))
    return cutouts


def _is_punctuation_value(value: str) -> bool:
    """Return True if the value is a single punctuation character/token."""
    return value.strip() in PUNCTUATION_NAMES


def _is_punctuation_name(name: str) -> bool:
    """Return True if the name itself represents a punctuation node."""
    return name.strip() in PUNCTUATION_NAMES


def _is_abstraction_prefix_only(nodes: list[NodePayload]) -> bool:
    """Return True if all non-punctuation nodes are abstraction-prefix values.

    A cutout is "abstraction-prefix only" if every node value starts with a
    known abstraction prefix (VAR_, LITERAL_, etc.) or is punctuation.
    """
    non_punct = [n for n in nodes if not (_is_punctuation_name(n.name) or _is_punctuation_value(n.value))]
    if not non_punct:
        return True
    return all(any(n.value.startswith(p) for p in ABSTRACTION_PREFIXES) for n in non_punct)


def _is_punctuation_only(nodes: list[NodePayload]) -> bool:
    """Return True if all nodes are punctuation."""
    return all(_is_punctuation_name(n.name) or _is_punctuation_value(n.value) for n in nodes)


def is_content_free(cutout: Cutout) -> bool:
    """Determine if a cutout is content-free and should be filtered out.

    A cutout is content-free if:
    - It has no nodes, OR
    - All nodes are punctuation, OR
    - All non-punctuation node values are abstraction prefixes only.

    Args:
        cutout: the Cutout to evaluate.

    Returns:
        True if the cutout should be excluded.
    """
    if not cutout.nodes:
        return True
    if _is_punctuation_only(cutout.nodes):
        return True
    if _is_abstraction_prefix_only(cutout.nodes):
        return True
    return False


def filter_cutouts(
    cutouts: list[Cutout],
) -> tuple[list[Cutout], list[Cutout]]:
    """Separate cutouts into valid and excluded lists.

    Args:
        cutouts: full list of Cutout objects.

    Returns:
        Tuple of (valid_cutouts, excluded_cutouts).
    """
    valid: list[Cutout] = []
    excluded: list[Cutout] = []

    for cutout in cutouts:
        if is_content_free(cutout):
            excluded.append(cutout)
        else:
            valid.append(cutout)

    logger.info(
        "Filtered: %d valid, %d excluded (content-free)",
        len(valid),
        len(excluded),
    )
    return valid, excluded


def save_filtered_out(excluded: list[Cutout], output_dir: Path) -> None:
    """Save excluded cutouts to filtered_out.json.

    Args:
        excluded: list of excluded Cutout objects.
        output_dir: directory to write filtered_out.json.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "filtered_out.json"
    records = [
        {
            "cutout_id": c.cutout_id,
            "mb_id": c.mb_id,
            "depth": c.depth,
            "node_count": len(c.nodes),
        }
        for c in excluded
    ]
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d filtered-out cutouts to %s", len(excluded), out_path)
