"""パターン抽出パイプライン Stage 5c: サイズ選択 (depth L*)。

MB ごとに depth L* を統合サイズスコアで選択する。抽象化 A はデータセット全体で固定される
（§6.6.3）ため、本モジュールでは L 軸のみ選ぶ。

公開 API:
    - select_optimal_depth(mb_id, cutouts_by_depth, weight_w): SelectionResult
"""

from __future__ import annotations

from hayalab.classes.pattern import Cutout, SelectionResult
from hayalab.config.pattern_config import DEFAULT_WEIGHT_W
from hayalab.pattern.scoring import compute_size_score


def select_optimal_depth(
    mb_id: int,
    cutouts_by_depth: dict[int, list[Cutout]],
    weight_w: float = DEFAULT_WEIGHT_W,
) -> SelectionResult:
    """MB ごとに最適な depth L* をサイズスコアで選択する。

    アルゴリズム:
        1. n_max = max over L of sum(|c.node_indices| for c in cutouts_by_depth[L])
        2. 各 depth L で compute_size_score(...) を計算
        3. L* = argmax_L score。同点は最小 L をタイブレーク（Occam's razor）。
        4. 全 depth で cutouts が空、または n_max == 0 の場合は "unrepresentable"。

    Args:
        mb_id: 対象 MB の id。
        cutouts_by_depth: depth (1..4) -> Cutout リスト。
        weight_w: ρ への重み w ∈ [0, 1]。

    Returns:
        SelectionResult。optimal_abst_level は呼び出し側で埋める前提のため None。
    """
    # n_max を算出
    n_max = 0
    for cutouts in cutouts_by_depth.values():
        n = sum(len(c.node_indices) for c in cutouts)
        if n > n_max:
            n_max = n

    if n_max == 0:
        return SelectionResult(
            mb_id=mb_id,
            optimal_depth=None,
            optimal_abst_level=None,
            status="unrepresentable",
            equivalence_class_id=None,
        )

    # 各 depth でスコアを計算し、最大スコアを取る最小 L を選ぶ
    best_depth: int | None = None
    best_score: float = -1.0
    for depth in sorted(cutouts_by_depth.keys()):
        cutouts = cutouts_by_depth[depth]
        if not cutouts:
            continue
        score = compute_size_score(cutouts, n_max, weight_w).score
        if score > best_score:
            best_score = score
            best_depth = depth

    if best_depth is None:
        return SelectionResult(
            mb_id=mb_id,
            optimal_depth=None,
            optimal_abst_level=None,
            status="unrepresentable",
            equivalence_class_id=None,
        )

    return SelectionResult(
        mb_id=mb_id,
        optimal_depth=best_depth,
        optimal_abst_level=None,
        status="selected",
        equivalence_class_id=None,
    )
