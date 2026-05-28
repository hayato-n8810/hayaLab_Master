"""Class representative export for §6 JSON schema.

Exports clustering results as classes_{level}_{method}.json files with
representative code, depth profiles, and incoming/outgoing transitions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ast_node import Cutout, TemplateNode
from observe import AllResults, _build_cutout_to_class, compute_depth_profile

logger = logging.getLogger(__name__)

# Placeholder tokens for representative string generation
PLACEHOLDERS: dict[str | None, str] = {
    "$var": "‹var›",
    "$lit": "‹lit›",
    "$func": "‹func›",
    None: "‹?›",
}


def make_representative_string(
    template: list[TemplateNode],
    level: int,
) -> str:
    """Generate a human-readable pseudocode string for a TemplateNode list.

    Uses slot_id and value to produce placeholder-annotated pseudocode.

    Args:
        template: list of TemplateNode from a Pattern.
        level: abstraction level (for context).

    Returns:
        Pseudocode string.
    """
    tokens: list[str] = []
    for t in template:
        if t.value is None:
            tokens.append(f"‹{t.name}›")
        elif t.slot_id is not None:
            tokens.append(t.slot_id)
        else:
            tokens.append(t.value)
    return " ".join(tokens)


def _diff_overlap_ratio(
    members: list[str],
    cutout_map: dict[str, Cutout],
) -> float:
    """Compute the fraction of member cutouts that are Diff-type.

    Args:
        members: list of cutout_ids.
        cutout_map: map from cutout_id to Cutout.

    Returns:
        Ratio of Diff cutouts in members.
    """
    if not members:
        return 0.0
    diff_count = sum(1 for cid in members if cutout_map.get(cid) and cutout_map[cid].depth == "Diff")
    return diff_count / len(members)


def _find_representative_pattern(
    members: list[str],
    patterns_by_id: dict[str, Any],
) -> list[dict]:
    """Find the representative pattern (smallest member) for a class.

    Args:
        members: list of cutout_ids.
        patterns_by_id: map from cutout_id → Pattern.

    Returns:
        TemplateNode list serialized as dicts (for the smallest member).
    """
    if not members:
        return []
    # Smallest by template length
    best_id = min(
        members,
        key=lambda cid: len(patterns_by_id[cid].ast_template) if cid in patterns_by_id else 9999,
    )
    pattern = patterns_by_id.get(best_id)
    if pattern is None:
        return []
    return [t.to_dict() for t in pattern.ast_template]


def export_classes(
    all_results: AllResults,
    cutouts: list[Cutout],
    patterns_by_level: dict[int, dict[str, Any]],
    output_dir: Path,
    levels: list[int] | None = None,
    methods: list[str] | None = None,
) -> None:
    """Export classes_{level}_{method}.json for all (level, method) combinations.

    Schema per class entry:
    {
        "class_id": str,
        "abst_level": int,
        "method": str,
        "size": int,
        "members": [cutout_id, ...],
        "depth_profile": {depth: count},
        "representative_ast": [TemplateNode dict, ...],
        "representative_string": str,
        "smallest_member_code": str,       # cutout_id of smallest member
        "incoming_classes": [class_id],    # classes at level-1 that map here
        "outgoing_class": str | null,      # class at level+1 this maps to
        "diff_overlap_ratio": float
    }

    Args:
        all_results: output of run_all().
        cutouts: list of Cutout objects (for depth info and diff_overlap_ratio).
        patterns_by_level: dict level → {cutout_id: Pattern}.
        output_dir: directory to write JSON files.
        levels: levels to export (default: all present).
        methods: methods to export (default: all present in first level).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if levels is None:
        levels = sorted(all_results.keys())
    if methods is None:
        first_level = levels[0] if levels else 0
        methods = list(all_results.get(first_level, {}).keys())

    cutout_map: dict[str, Cutout] = {c.cutout_id: c for c in cutouts}

    for level in levels:
        for method in methods:
            classes = all_results.get(level, {}).get(method, {})
            patterns_map = patterns_by_level.get(level, {})

            # Build outgoing (level+1) mapping
            next_level = level + 1
            next_classes = all_results.get(next_level, {}).get(method, {})
            next_mapping = _build_cutout_to_class(next_classes) if next_classes else {}

            # Build incoming (level-1) mapping
            prev_level = level - 1
            prev_classes = all_results.get(prev_level, {}).get(method, {})

            # For each class at this level, find which prev classes map into it
            curr_class_map = _build_cutout_to_class(classes)
            class_to_prev: dict[str, set[str]] = {cid: set() for cid in classes}
            for prev_class_id, prev_members in prev_classes.items():
                for cid in prev_members:
                    curr_class = curr_class_map.get(cid)
                    if curr_class and curr_class in class_to_prev:
                        class_to_prev[curr_class].add(prev_class_id)

            records: list[dict] = []

            for class_id, members in sorted(classes.items()):
                # Representative: smallest member
                rep_ast = _find_representative_pattern(members, patterns_map)
                smallest_cid = min(
                    members,
                    key=lambda cid: len(patterns_map[cid].ast_template) if cid in patterns_map else 9999,
                )
                rep_str = ""
                if smallest_cid in patterns_map:
                    rep_str = make_representative_string(patterns_map[smallest_cid].ast_template, level)

                # Outgoing class: the class at level+1 that the first member maps to
                outgoing: str | None = None
                if members and next_mapping:
                    outgoing_classes = {next_mapping.get(cid) for cid in members}
                    outgoing_classes.discard(None)
                    outgoing = sorted(outgoing_classes)[0] if outgoing_classes else None

                records.append(
                    {
                        "class_id": class_id,
                        "abst_level": level,
                        "method": method,
                        "size": len(members),
                        "members": members,
                        "depth_profile": compute_depth_profile(members),
                        "representative_ast": rep_ast,
                        "representative_string": rep_str,
                        "smallest_member_code": smallest_cid,
                        "incoming_classes": sorted(class_to_prev.get(class_id, set())),
                        "outgoing_class": outgoing,
                        "diff_overlap_ratio": _diff_overlap_ratio(members, cutout_map),
                    }
                )

            out_path = output_dir / f"classes_A{level}_{method}.json"
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
            logger.info("Exported %d classes to %s", len(records), out_path)
