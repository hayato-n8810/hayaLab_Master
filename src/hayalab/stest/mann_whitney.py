"""マンホイットニーのU検定とクリフデルタによる効果量計算"""

from typing import Dict, List

import numpy as np
from scipy import stats


def cliff_delta(baseline: List[float], target: List[float]) -> float:
    """クリフデルタ（効果量）を計算

    Args:
        baseline(List[float]): 基準となるデータのリスト
        target(List[float]): 比較対象のデータのリスト

    Returns:
        float: クリフデルタの値
    """

    baseline_arr = np.array(baseline)
    target_arr = np.array(target)

    n1 = len(baseline_arr)
    n2 = len(target_arr)

    # すべてのペアの比較
    more = 0
    less = 0

    for b in baseline_arr:
        for t in target_arr:
            if b > t:
                more += 1
            elif b < t:
                less += 1

    delta = (more - less) / (n1 * n2)
    return delta


def mann_whitney_test(baseline: List[float], target: List[float], alpha: float = 0.05) -> Dict[str, float | bool]:
    """マンホイットニーのU検定を実行

    Args:
        baseline(List[float]): 基準となるデータのリスト（数値）
        target(List[float]): 検定を行う対象のデータのリスト（数値）
        alpha(float): 有意水準（デフォルト: 0.05）

    Returns:
        Dict[str, float | bool]: 検定結果を含む辞書
            - is_significant: 検定結果（有意差あり: True, 有意差なし: False）
            - p_value: p値
            - cliff_delta: 効果量（クリフデルタ）
            - u_statistic: U統計量
            - alpha: 有意水準
    """
    # 入力検証
    if not baseline or not target:
        raise ValueError("データリストが空")

    if not (0 < alpha < 1):
        raise ValueError("有意水準は 0 < alpha < 1 の範囲で指定してください")

    # マンホイットニーのU検定
    # alternative='two-sided'で両側検定を実行
    statistic, p_value = stats.mannwhitneyu(baseline, target, alternative="two-sided")

    # 効果量（クリフデルタ）を計算
    delta = cliff_delta(baseline, target)

    # 有意差の判定
    is_significant = p_value < alpha

    return {"significant": is_significant, "p_value": p_value, "cliff_delta": delta, "u_statistic": statistic, "alpha": alpha}
