"""Evaluation metrics: Purity, NMI, ARI.

Computes clustering quality metrics against ground-truth labels.
If ground truth is not available, functions can be used individually for
spot-checking or left unused.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from typing import Any

from observe import AllResults

logger = logging.getLogger(__name__)


def compute_purity(
    class_members: dict[str, list[str]],
    ground_truth_labels: dict[str, str],
) -> float:
    """Compute clustering purity.

    Purity = (1/N) * sum_k max_j |C_k ∩ L_j|

    Args:
        class_members: dict class_id → list of cutout_ids.
        ground_truth_labels: dict cutout_id → ground-truth class label.

    Returns:
        Purity in [0, 1].
    """
    total = sum(len(m) for m in class_members.values())
    if total == 0:
        return 0.0

    total_max = 0
    for members in class_members.values():
        label_counts = Counter(ground_truth_labels.get(cid, "__unknown__") for cid in members)
        total_max += max(label_counts.values()) if label_counts else 0

    return total_max / total


def compute_nmi(
    class_members: dict[str, list[str]],
    ground_truth_labels: dict[str, str],
) -> float:
    """Compute Normalized Mutual Information (NMI).

    NMI = 2 * I(C; L) / (H(C) + H(L))

    Args:
        class_members: dict class_id → list of cutout_ids.
        ground_truth_labels: dict cutout_id → ground-truth class label.

    Returns:
        NMI in [0, 1].
    """
    all_cutouts = [cid for m in class_members.values() for cid in m]
    n = len(all_cutouts)
    if n == 0:
        return 0.0

    # Cluster assignment
    cutout_to_cluster: dict[str, str] = {}
    for cls, members in class_members.items():
        for cid in members:
            cutout_to_cluster[cid] = cls

    cluster_labels = [cutout_to_cluster.get(cid, "__unknown__") for cid in all_cutouts]
    gt_labels = [ground_truth_labels.get(cid, "__unknown__") for cid in all_cutouts]

    cluster_counts = Counter(cluster_labels)
    gt_counts = Counter(gt_labels)

    # Joint counts
    joint_counts: Counter = Counter(zip(cluster_labels, gt_labels))

    # Mutual information
    mi = 0.0
    for (c, label), count in joint_counts.items():
        p_cl = count / n
        p_c = cluster_counts[c] / n
        p_l = gt_counts[label] / n
        if p_cl > 0 and p_c > 0 and p_l > 0:
            mi += p_cl * math.log(p_cl / (p_c * p_l))

    # Entropies
    h_c = -sum((cnt / n) * math.log(cnt / n) for cnt in cluster_counts.values() if cnt > 0)
    h_l = -sum((cnt / n) * math.log(cnt / n) for cnt in gt_counts.values() if cnt > 0)

    denom = (h_c + h_l) / 2
    if denom == 0:
        return 1.0
    return mi / denom


def compute_ari(
    class_members: dict[str, list[str]],
    ground_truth_labels: dict[str, str],
) -> float:
    """Compute Adjusted Rand Index (ARI).

    ARI = (RI - E[RI]) / (max(RI) - E[RI])

    Uses the combinatorial formula based on contingency table.

    Args:
        class_members: dict class_id → list of cutout_ids.
        ground_truth_labels: dict cutout_id → ground-truth class label.

    Returns:
        ARI in [-1, 1] (1 = perfect clustering).
    """
    all_cutouts = [cid for m in class_members.values() for cid in m]
    n = len(all_cutouts)
    if n == 0:
        return 0.0

    cutout_to_cluster: dict[str, str] = {}
    for cls, members in class_members.items():
        for cid in members:
            cutout_to_cluster[cid] = cls

    cluster_ids = [cutout_to_cluster.get(cid, "__unknown__") for cid in all_cutouts]
    gt_ids = [ground_truth_labels.get(cid, "__unknown__") for cid in all_cutouts]

    # Contingency table
    contingency: Counter = Counter(zip(cluster_ids, gt_ids))
    cluster_sums = Counter(cluster_ids)
    gt_sums = Counter(gt_ids)

    def comb2(x: int) -> int:
        return x * (x - 1) // 2

    sum_comb_nij = sum(comb2(count) for count in contingency.values())
    sum_comb_ai = sum(comb2(count) for count in cluster_sums.values())
    sum_comb_bj = sum(comb2(count) for count in gt_sums.values())
    comb_n = comb2(n)

    if comb_n == 0:
        return 1.0

    expected = sum_comb_ai * sum_comb_bj / comb_n
    max_val = (sum_comb_ai + sum_comb_bj) / 2
    denom = max_val - expected

    if denom == 0:
        return 1.0 if sum_comb_nij == expected else 0.0

    return (sum_comb_nij - expected) / denom


def evaluate_all(
    all_results: AllResults,
    ground_truth: dict[str, str],
    levels: list[int] | None = None,
    methods: list[str] | None = None,
) -> dict[str, Any]:
    """Compute Purity, NMI, ARI for all (level, method) combinations.

    Args:
        all_results: output of run_all().
        ground_truth: dict cutout_id → ground-truth label string.
        levels: levels to evaluate (default: all).
        methods: methods to evaluate (default: all in first level).

    Returns:
        Dict keyed by "{level}_{method}" with Purity, NMI, ARI values.
    """
    if levels is None:
        levels = sorted(all_results.keys())
    if methods is None and levels:
        methods = list(all_results[levels[0]].keys())
    if methods is None:
        methods = []

    results: dict[str, Any] = {}
    for level in levels:
        for method in methods:
            classes = all_results.get(level, {}).get(method, {})
            if not classes:
                continue
            purity = compute_purity(classes, ground_truth)
            nmi = compute_nmi(classes, ground_truth)
            ari = compute_ari(classes, ground_truth)
            key = f"A{level}_{method}"
            results[key] = {
                "level": level,
                "method": method,
                "n_classes": len(classes),
                "purity": round(purity, 4),
                "nmi": round(nmi, 4),
                "ari": round(ari, 4),
            }
            logger.info(
                "Eval %s: purity=%.4f, nmi=%.4f, ari=%.4f",
                key,
                purity,
                nmi,
                ari,
            )

    return results
