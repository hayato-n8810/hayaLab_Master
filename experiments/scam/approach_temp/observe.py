"""Aggregation runner and trajectory builder.

Runs all (level, method) combinations and builds per-cutout trajectory
records for Sankey visualization and further analysis.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from abstract import abstract_cutout
from ast_node import Cutout, Pattern
from methods.m0_hash import cluster_m0
from methods.m1_inclusion import cluster_m1
from methods.m2_bi_inclusion import cluster_m2
from methods.m3_antiunify import cluster_m3

logger = logging.getLogger(__name__)

# Supported abstraction levels and methods
ALL_LEVELS = list(range(6))  # 0..5
ALL_METHODS = ["M0", "M1", "M2", "M3"]

# Type alias: AllResults[level][method] = {class_id: [cutout_id]}
AllResults = dict[int, dict[str, dict[str, list[str]]]]


def _apply_cluster(patterns: list[Pattern], method: str) -> dict[str, list[str]]:
    """Apply a single clustering method to a list of patterns.

    Extracted as a standalone function to be usable from both sequential
    and parallel code paths.

    Args:
        patterns: abstracted patterns for one level.
        method: one of "M0", "M1", "M2", "M3".

    Returns:
        Dict class_id -> list of cutout_ids.
    """
    if method == "M0":
        return cluster_m0(patterns)
    elif method == "M1":
        return cluster_m1(patterns)
    elif method == "M2":
        return cluster_m2(patterns)
    elif method == "M3":
        return cluster_m3(patterns)
    else:
        return {}


def _run_one_task(
    args: tuple[list[Cutout], int, str],
) -> tuple[int, str, dict[str, list[str]]]:
    """Worker function for parallel execution of one (level, method) task.

    Must be a module-level function for ProcessPoolExecutor pickling.

    Args:
        args: (cutouts, level, method)

    Returns:
        (level, method, classes_dict)
    """
    cutouts, level, method = args
    patterns: list[Pattern] = [abstract_cutout(c, level) for c in cutouts]
    classes = _apply_cluster(patterns, method)
    return level, method, classes


def run_all(
    cutouts: list[Cutout],
    levels: list[int] | None = None,
    methods: list[str] | None = None,
    workers: int = 1,
) -> AllResults:
    """Run all (level, method) combinations.

    Each (level, method) pair is independent and can be executed in parallel.
    With workers=1 (default) the execution is sequential.
    With workers>1 a ProcessPoolExecutor is used.

    Args:
        cutouts: list of valid (non-filtered) Cutout objects.
        levels: abstraction levels to run (default: 0-5).
        methods: method names to run (default: M0-M3).
        workers: number of parallel worker processes (1 = sequential).

    Returns:
        Nested dict AllResults[level][method] = {class_id: [cutout_id]}.
    """
    if levels is None:
        levels = ALL_LEVELS
    if methods is None:
        methods = ALL_METHODS

    results: AllResults = {level: {} for level in levels}
    tasks = [(cutouts, lv, m) for lv in levels for m in methods]
    n_tasks = len(tasks)

    if workers <= 1:
        # ---- Sequential execution ----------------------------------------
        for i, (cutouts_, level, method) in enumerate(tasks, 1):
            logger.info("[%d/%d] Abstracting A%d + clustering %s ...", i, n_tasks, level, method)
            patterns: list[Pattern] = [abstract_cutout(c, level) for c in cutouts_]
            classes = _apply_cluster(patterns, method)
            results[level][method] = classes
            logger.info("    → %d classes for %d patterns", len(classes), len(patterns))
    else:
        # ---- Parallel execution ------------------------------------------
        logger.info("Parallel mode: %d tasks across %d workers ...", n_tasks, workers)
        completed = 0
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_task = {executor.submit(_run_one_task, task): task for task in tasks}
            for future in as_completed(future_to_task):
                level, method, classes = future.result()
                results[level][method] = classes
                completed += 1
                _, lv, m = future_to_task[future]
                logger.info(
                    "[%d/%d] Done: A%d × %s → %d classes",
                    completed,
                    n_tasks,
                    lv,
                    m,
                    len(classes),
                )

    return results


def _build_cutout_to_class(
    classes: dict[str, list[str]],
) -> dict[str, str]:
    """Invert classes dict to map cutout_id → class_id."""
    mapping: dict[str, str] = {}
    for class_id, members in classes.items():
        for cid in members:
            mapping[cid] = class_id
    return mapping


def build_trajectory(
    all_results: AllResults,
    method: str,
    levels: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Build per-cutout trajectory records for a given method.

    Each trajectory record contains the cutout_id and the class_id assigned
    at each abstraction level.

    Args:
        all_results: output of run_all().
        method: method name (e.g. "M0").
        levels: list of levels to include (default: all present levels).

    Returns:
        List of trajectory dicts, one per cutout_id:
        {
            "cutout_id": str,
            "mb_id": int,
            "depth": str,
            "trajectory": { "0": class_id, "1": class_id, ... }
        }
    """
    if levels is None:
        levels = sorted(all_results.keys())

    # Collect all cutout_ids from first available level
    first_level = levels[0]
    first_classes = all_results.get(first_level, {}).get(method, {})
    all_cutout_ids: set[str] = set()
    for members in first_classes.values():
        all_cutout_ids.update(members)
    # Also collect from remaining levels (in case some appear only at higher levels)
    for lv in levels[1:]:
        for members in all_results.get(lv, {}).get(method, {}).values():
            all_cutout_ids.update(members)

    # Build level→mapping
    level_mappings: dict[int, dict[str, str]] = {}
    for lv in levels:
        classes = all_results.get(lv, {}).get(method, {})
        level_mappings[lv] = _build_cutout_to_class(classes)

    trajectories: list[dict[str, Any]] = []
    for cid in sorted(all_cutout_ids):
        parts = cid.split("_", 1)
        mb_id = int(parts[0]) if parts[0].isdigit() else -1
        depth = parts[1] if len(parts) > 1 else ""
        traj: dict[str, str] = {}
        for lv in levels:
            traj[str(lv)] = level_mappings[lv].get(cid, "UNKNOWN")
        trajectories.append(
            {
                "cutout_id": cid,
                "mb_id": mb_id,
                "depth": depth,
                "trajectory": traj,
            }
        )

    return trajectories


def compute_depth_profile(class_members: list[str]) -> dict[str, int]:
    """Compute depth distribution of members in a class.

    Args:
        class_members: list of cutout_id strings.

    Returns:
        Dict mapping depth name → count.
    """
    profile: dict[str, int] = {}
    for cid in class_members:
        parts = cid.split("_", 1)
        depth = parts[1] if len(parts) > 1 else "unknown"
        profile[depth] = profile.get(depth, 0) + 1
    return profile


def compute_transition_matrix(
    trajectories: list[dict[str, Any]],
    level_k: int,
    level_k1: int,
) -> dict[str, dict[str, int]]:
    """Compute the transition matrix between two abstraction levels.

    Args:
        trajectories: output of build_trajectory().
        level_k: source level.
        level_k1: target level.

    Returns:
        Nested dict: {class_id_at_k: {class_id_at_k1: count}}.
    """
    matrix: dict[str, dict[str, int]] = {}
    for entry in trajectories:
        src = entry["trajectory"].get(str(level_k), "UNKNOWN")
        dst = entry["trajectory"].get(str(level_k1), "UNKNOWN")
        matrix.setdefault(src, {})
        matrix[src][dst] = matrix[src].get(dst, 0) + 1
    return matrix


def save_trajectory(
    trajectories: list[dict[str, Any]],
    method: str,
    output_dir: Path,
) -> Path:
    """Save trajectory records to trajectory_{method}.json.

    Args:
        trajectories: output of build_trajectory().
        method: method name.
        output_dir: directory to write into.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"trajectory_{method}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(trajectories, f, indent=2, ensure_ascii=False)
    logger.info("Saved trajectory for %s: %d entries → %s", method, len(trajectories), out_path)
    return out_path


def check_monotonicity(
    all_results: AllResults,
    method: str,
    levels: list[int] | None = None,
) -> int:
    """Check monotonicity violations for a given method.

    A violation occurs when two cutouts that are in the same class at level k
    are in different classes at level k+1 (abstraction should only merge, never split).

    Args:
        all_results: output of run_all().
        method: method name.
        levels: ordered list of levels (default: sorted keys of all_results).

    Returns:
        Number of monotonicity violations found.
    """
    if levels is None:
        levels = sorted(all_results.keys())

    violations = 0
    for i in range(len(levels) - 1):
        lk, lk1 = levels[i], levels[i + 1]
        classes_k = all_results.get(lk, {}).get(method, {})
        classes_k1 = all_results.get(lk1, {}).get(method, {})

        # Build cutout → class mapping at k+1
        mapping_k1 = _build_cutout_to_class(classes_k1)

        for _class_id_k, members_k in classes_k.items():
            # All members of a class at level k must be in the same class at k+1
            classes_at_k1 = {mapping_k1.get(cid, "UNKNOWN") for cid in members_k}
            if len(classes_at_k1) > 1:
                violations += 1
                logger.warning(
                    "Monotonicity violation: class at L%d splits at L%d into %s",
                    lk,
                    lk1,
                    classes_at_k1,
                )

    if violations > 0:
        if method == "M0":
            # M0 (hash exact match) must be strictly monotone — violations = bugs
            logger.warning(
                "Method %s: %d monotonicity violations detected (implementation bug!)",
                method,
                violations,
            )
        else:
            # M1/M2/M3: similarity-based clustering; re-assignment across levels is
            # expected per spec §5.1 ("観察対象として記録する").
            logger.info(
                "Method %s: %d class re-assignments across levels (expected behavior for similarity-based clustering per §5.1).",
                method,
                violations,
            )
    else:
        logger.info("Method %s: no monotonicity violations.", method)

    return violations
