"""Loader for outputs/scam/approach/03_abstract/03_abstract_level{L}.json.

Each input file has the schema::

    [
      {
        "id": <mb_id>,
        "cutouts": {
          "Diff":   {"diff_node_indices": [...], "nodes": [<TemplateNode dict>...]},
          "Brother": {...},
          "ExParent": {...},
          "Parent":  {...}
        }
      },
      ...
    ]

The ``nodes`` payload is already in TemplateNode-compatible form (with
``slot_id``, ``variadic``).  Older payloads stored ``parent`` rather than
``parent_relative``; :func:`TemplateNode.from_dict` handles both keys.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ast_node import Pattern, TemplateNode

logger = logging.getLogger(__name__)

DEPTH_KEYS = ("Diff", "Brother", "ExParent", "Parent")


def load_patterns_for_level(
    path: Path,
    level: int,
    sample_mb_ids: set[int] | None = None,
    sample_n: int | None = None,
) -> list[Pattern]:
    """Load all patterns from ``03_abstract_level{level}.json``.

    Args:
        path: path to the JSON file.
        level: abstraction level (0-3); used to tag :attr:`Pattern.abst_level`.
        sample_mb_ids: if given, only records whose ``id`` is in this set are
            loaded.  Use this to ensure all abstraction levels share the same
            mb_id subset (callers compute the set from the first level).
        sample_n: if given (and ``sample_mb_ids`` is None), keep only the first
            ``sample_n`` records in file order (matches approach_temp's
            ``--sample`` semantics).

    Returns:
        Flat list of :class:`Pattern` (one per (mb_id, depth)).
    """
    logger.info("Loading patterns from %s (level=%d)...", path, level)
    with path.open(encoding="utf-8") as f:
        records = json.load(f)

    if sample_mb_ids is not None:
        records = [r for r in records if r["id"] in sample_mb_ids]
        logger.info("  filtered by sample_mb_ids: %d records", len(records))
    elif sample_n is not None and sample_n > 0:
        records = records[:sample_n]
        logger.info("  truncated to first %d records", len(records))

    patterns: list[Pattern] = []
    for rec in records:
        mb_id = rec["id"]
        cutouts = rec.get("cutouts", {})
        for depth in DEPTH_KEYS:
            cd = cutouts.get(depth)
            if not cd:
                continue
            nodes = cd.get("nodes") or []
            tnodes = [TemplateNode.from_dict(n) for n in nodes]
            # Mark is_terminal from parent presence in cutout.
            parent_indices = {n.parent_relative[-1] for n in tnodes if n.parent_relative}
            for n in tnodes:
                n.is_terminal = n.origin_index not in parent_indices
            patterns.append(
                Pattern(
                    mb_id=mb_id,
                    depth=depth,
                    abst_level=level,
                    ast_template=tnodes,
                    diff_node_indices=cd.get("diff_node_indices", []),
                )
            )
    logger.info("  loaded %d patterns at L%d", len(patterns), level)
    return patterns


def filter_empty_patterns(patterns: list[Pattern], min_nodes: int = 2) -> tuple[list[Pattern], list[dict]]:
    """Drop patterns whose template has fewer than ``min_nodes`` nodes.

    Returns (kept, excluded_records).  The excluded records mirror
    approach_temp's ``filtered_out.json`` schema.
    """
    kept: list[Pattern] = []
    excluded: list[dict] = []
    for p in patterns:
        n = len(p.ast_template)
        if n < min_nodes:
            excluded.append(
                {
                    "cutout_id": p.cutout_id,
                    "mb_id": p.mb_id,
                    "depth": p.depth,
                    "node_count": n,
                }
            )
        else:
            kept.append(p)
    return kept, excluded
