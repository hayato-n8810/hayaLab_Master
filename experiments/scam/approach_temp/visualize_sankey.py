"""Sankey diagram visualization for clustering trajectories.

Generates an interactive HTML Sankey diagram showing how cutouts move between
classes as the abstraction level increases from A0 to A5.

Requires: plotly (uv add plotly)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_trajectory(path: str | Path) -> list[dict[str, Any]]:
    """Load a trajectory_{method}.json file.

    Args:
        path: path to the trajectory JSON file.

    Returns:
        List of trajectory entry dicts.
    """
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def build_sankey_data(
    trajectories: list[dict[str, Any]],
    levels: list[int] | None = None,
) -> tuple[list[str], list[int], list[int], list[int]]:
    """Build Plotly Sankey data from trajectory records.

    Creates one Sankey node per (level, class_id) pair, and one flow for each
    cutout transition between consecutive levels.

    Args:
        trajectories: output of load_trajectory().
        levels: ordered list of levels to visualize. If None, auto-detected.

    Returns:
        Tuple of (node_labels, source_indices, target_indices, values).
        node_labels[i]: label for Sankey node i.
        source_indices[i], target_indices[i]: flow edge i.
        values[i]: flow weight (number of cutouts in the transition).
    """
    if not trajectories:
        return [], [], [], []

    # Auto-detect levels from first entry
    if levels is None:
        first_traj = trajectories[0]["trajectory"]
        levels = sorted(int(k) for k in first_traj.keys())

    # Collect all (level, class_id) pairs in order
    level_to_classes: dict[int, list[str]] = {}
    for lv in levels:
        seen: set[str] = set()
        ordered: list[str] = []
        for entry in trajectories:
            cid = entry["trajectory"].get(str(lv), "UNKNOWN")
            if cid not in seen:
                seen.add(cid)
                ordered.append(cid)
        level_to_classes[lv] = ordered

    # Build node index mapping: (level, class_id) → node_index
    node_labels: list[str] = []
    node_index: dict[tuple[int, str], int] = {}

    for lv in levels:
        for cls_id in level_to_classes[lv]:
            label = f"A{lv}: {cls_id[-12:]}"  # truncate for readability
            node_index[(lv, cls_id)] = len(node_labels)
            node_labels.append(label)

    # Build flows: for each consecutive pair of levels, count transitions
    source_list: list[int] = []
    target_list: list[int] = []
    value_list: list[int] = []

    for i in range(len(levels) - 1):
        lk, lk1 = levels[i], levels[i + 1]
        flow_counts: dict[tuple[str, str], int] = {}
        for entry in trajectories:
            src_cls = entry["trajectory"].get(str(lk), "UNKNOWN")
            dst_cls = entry["trajectory"].get(str(lk1), "UNKNOWN")
            flow_counts[(src_cls, dst_cls)] = flow_counts.get((src_cls, dst_cls), 0) + 1

        for (src_cls, dst_cls), count in flow_counts.items():
            src_idx = node_index.get((lk, src_cls))
            dst_idx = node_index.get((lk1, dst_cls))
            if src_idx is not None and dst_idx is not None:
                source_list.append(src_idx)
                target_list.append(dst_idx)
                value_list.append(count)

    return node_labels, source_list, target_list, value_list


def render_sankey(
    method: str,
    trajectories: list[dict[str, Any]],
    output_path: Path,
    levels: list[int] | None = None,
) -> None:
    """Render a Sankey diagram to an HTML file.

    Args:
        method: method name (shown in title).
        trajectories: output of load_trajectory().
        output_path: path to write the HTML file.
        levels: levels to include (default: all).
    """
    try:
        import plotly.graph_objects as go  # type: ignore[import]
    except ImportError as e:
        logger.error("plotly is required for Sankey visualization. Run: uv add plotly. Error: %s", e)
        raise

    node_labels, sources, targets, values = build_sankey_data(trajectories, levels)

    if not node_labels:
        logger.warning("No data to visualize for method %s", method)
        return

    # Assign x positions per level so nodes are arranged left-to-right
    if levels is None:
        first_traj = trajectories[0]["trajectory"] if trajectories else {}
        levels = sorted(int(k) for k in first_traj.keys())

    level_to_classes: dict[int, list[str]] = {}
    for lv in levels:
        seen: set[str] = set()
        ordered: list[str] = []
        for entry in trajectories:
            cid = entry["trajectory"].get(str(lv), "UNKNOWN")
            if cid not in seen:
                seen.add(cid)
                ordered.append(cid)
        level_to_classes[lv] = ordered

    # Build x/y positions
    x_positions: list[float] = []
    y_positions: list[float] = []
    n_levels = len(levels)

    node_idx_counter = 0
    for i, lv in enumerate(levels):
        classes = level_to_classes[lv]
        n_classes = len(classes)
        x_val = i / max(n_levels - 1, 1) if n_levels > 1 else 0.5
        for j, _ in enumerate(classes):
            x_positions.append(round(x_val, 4) + 0.0001)  # slight offset to avoid 0/1
            y_positions.append(round((j + 1) / (n_classes + 1), 4) + 0.0001)
            node_idx_counter += 1

    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node=dict(
                pad=15,
                thickness=20,
                line=dict(color="black", width=0.5),
                label=node_labels,
                x=x_positions,
                y=y_positions,
                hovertemplate="Class: %{label}<br>Cutouts: %{value}<extra></extra>",
            ),
            link=dict(
                source=sources,
                target=targets,
                value=values,
                hovertemplate=("From: %{source.label}<br>To: %{target.label}<br>Cutouts: %{value}<extra></extra>"),
            ),
        )
    )

    fig.update_layout(
        title_text=f"Slow Pattern Clustering — {method} (A0→A{max(levels)})",
        title_x=0.5,
        font_size=12,
        height=max(600, 40 * max(len(v) for v in level_to_classes.values())),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path))
    logger.info("Sankey HTML saved to %s", output_path)
