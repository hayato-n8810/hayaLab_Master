"""パターン抽出パイプライン Stage 5a: サイズスコアリング (ρ, σ, S)。

同一 MB・同一 depth の Cutout 群を入力に取り、Diff Density Ratio (ρ) と
Normalized Node Count (σ) を計算し、統合サイズスコア S(L) = w·ρ + (1-w)·σ を返す。

公開 API:
    - compute_rho(cutouts): float
    - compute_sigma(cutouts, n_max): float
    - compute_size_score(cutouts, n_max, weight_w): SizeScore
"""

from __future__ import annotations

from hayalab.classes.pattern import Cutout, SizeScore


def compute_rho(cutouts: list[Cutout]) -> float:
    """Diff Density Ratio を計算する。

    ρ(L) = sum(|Δ ∩ N(L)|) / sum(|N(L)|)（同一 MB・同一 depth 内で集計）。

    Args:
        cutouts: 同一 MB・同一 depth から得られた Cutout のリスト。

    Returns:
        rho ∈ [0, 1]。cutouts が空または総ノード数 0 のときは 0.0。
    """
    total_nodes = sum(len(c.node_indices) for c in cutouts)
    if total_nodes == 0:
        return 0.0
    diff_nodes = sum(len(c.diff_node_indices) for c in cutouts)
    return diff_nodes / total_nodes


def compute_sigma(cutouts: list[Cutout], n_max: int) -> float:
    """Normalized Node Count を計算する。

    σ(L) = sum(|c.node_indices| for c in cutouts) / n_max。

    Args:
        cutouts: 同一 MB・同一 depth から得られた Cutout のリスト。
        n_max: 同一 MB の 4 depth 中で最大のノード数（呼び出し側で算出）。

    Returns:
        sigma ∈ [0, 1]。n_max == 0 のときは 0.0。
    """
    if n_max <= 0:
        return 0.0
    total_nodes = sum(len(c.node_indices) for c in cutouts)
    return total_nodes / n_max


def compute_size_score(
    cutouts: list[Cutout],
    n_max: int,
    weight_w: float,
) -> SizeScore:
    """統合サイズスコア S(L) = w·ρ + (1-w)·σ を計算する。

    Args:
        cutouts: 同一 MB・同一 depth の Cutout 群。
        n_max: 同一 MB の 4 depth 中で最大のノード数。
        weight_w: ρ への重み w ∈ [0, 1]。

    Returns:
        SizeScore オブジェクト。

    Raises:
        ValueError: weight_w が [0, 1] の範囲外。
    """
    if not (0.0 <= weight_w <= 1.0):
        raise ValueError(f"weight_w must be in [0, 1], got {weight_w}")
    rho = compute_rho(cutouts)
    sigma = compute_sigma(cutouts, n_max)
    score = weight_w * rho + (1.0 - weight_w) * sigma
    return SizeScore(rho=rho, sigma=sigma, score=score, weight_w=weight_w)
