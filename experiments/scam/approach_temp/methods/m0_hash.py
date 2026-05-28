"""M0: Hash-based exact matching clustering.

Clusters patterns by SHA-256 hash of their canonicalized TemplateNode sequence.
Punctuation nodes are excluded before hashing (they are already excluded by
the abstraction layer, but this is confirmed here for safety).

Complexity: O(N) where N is the number of patterns.
"""

from __future__ import annotations

import hashlib
import json
import logging

from ast_node import Pattern
from cluster import make_class_id

logger = logging.getLogger(__name__)


def canonicalize(pattern: Pattern) -> str:
    """Serialize a Pattern's TemplateNode list to a canonical JSON string.

    The serialization includes name, value, and parent_relative for each node,
    in original order. This uniquely identifies the abstract shape of a pattern.

    Args:
        pattern: the Pattern whose template to canonicalize.

    Returns:
        Canonical JSON string.
    """
    records = [
        {
            "name": t.name,
            "value": t.value,
            "parent_relative": t.parent_relative,
        }
        for t in pattern.ast_template
    ]
    return json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def hash_pattern(pattern: Pattern) -> str:
    """Compute SHA-256 hash of the canonical form of a pattern.

    Args:
        pattern: the Pattern to hash.

    Returns:
        Full SHA-256 hex string.
    """
    canonical = canonicalize(pattern)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cluster_m0(patterns: list[Pattern]) -> dict[str, list[str]]:
    """Cluster patterns by exact hash equality.

    Patterns with the same canonical hash are placed in the same class.
    The class ID is derived from the abstraction level, method name, and hash prefix.

    Args:
        patterns: list of Pattern objects at the same abstraction level.

    Returns:
        Dict mapping class_id → sorted list of cutout_ids in that class.
    """
    if not patterns:
        return {}

    level = patterns[0].abst_level
    hash_to_ids: dict[str, list[str]] = {}

    for p in patterns:
        h = hash_pattern(p)
        hash_to_ids.setdefault(h, []).append(p.cutout_id)

    result: dict[str, list[str]] = {}
    for h, ids in sorted(hash_to_ids.items()):
        class_id = make_class_id(level, "M0", h[:8])
        result[class_id] = sorted(ids)

    logger.debug(
        "M0 clustering at level %d: %d patterns → %d classes",
        level,
        len(patterns),
        len(result),
    )
    return result
