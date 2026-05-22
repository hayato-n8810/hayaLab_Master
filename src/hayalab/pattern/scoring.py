"""パターン抽出パイプライン Stage 5a: サイズスコアリング (ρ, σ, S)。

1 MB × 1 depth につき 1 つの Cutout を入力に取り、Diff Density Ratio (ρ) と
Normalized Node Count (σ) を計算し、統合サイズスコア S(L) = w·ρ + (1-w)·σ を返す。

公開 API:
    - compute_rho(cutout): float
    - compute_sigma(cutout, n_max): float
    - compute_size_score(cutout, n_max, weight_w): SizeScore
"""

from __future__ import annotations

from hayalab.classes.pattern import Cutout, SizeScore


def compute_rho(cutout: Cutout) -> float:
    """Diff Density Ratio を計算する。

    ρ(L) = |Δ ∩ N(L)| / |N(L)|。

    Args:
        cutout: 同一 MB・同一 depth の Cutout。

    Returns:
        rho ∈ [0, 1]。総ノード数 0 のときは 0.0。
    """
    total_nodes = len(cutout.node_indices)
    if total_nodes == 0:
        return 0.0
    return len(cutout.diff_node_indices) / total_nodes


def compute_sigma(cutout: Cutout, n_max: int) -> float:
    """Normalized Node Count を計算する。

    σ(L) = |N(L)| / n_max。

    Args:
        cutout: 同一 MB・同一 depth の Cutout。
        n_max: 同一 MB の 4 depth 中で最大のノード数（呼び出し側で算出）。

    Returns:
        sigma ∈ [0, 1]。n_max == 0 のときは 0.0。
    """
    if n_max <= 0:
        return 0.0
    return len(cutout.node_indices) / n_max


def compute_size_score(
    cutout: Cutout,
    n_max: int,
    weight_w: float,
) -> SizeScore:
    """統合サイズスコア S(L) = w·ρ + (1-w)·σ を計算する。

    Args:
        cutout: 同一 MB・同一 depth の Cutout。
        n_max: 同一 MB の 4 depth 中で最大のノード数。
        weight_w: ρ への重み w ∈ [0, 1]。

    Returns:
        SizeScore オブジェクト。

    Raises:
        ValueError: weight_w が [0, 1] の範囲外。
    """
    if not (0.0 <= weight_w <= 1.0):
        raise ValueError(f"weight_w must be in [0, 1], got {weight_w}")
    rho = compute_rho(cutout)
    sigma = compute_sigma(cutout, n_max)
    score = weight_w * rho + (1.0 - weight_w) * sigma
    return SizeScore(rho=rho, sigma=sigma, score=score, weight_w=weight_w)
