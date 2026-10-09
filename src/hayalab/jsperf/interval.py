"""jsPerf 計測サンプルの信頼区間算出とペア抽出ユニット群。

計測結果 (samples_ns) から平均の信頼区間を求め、信頼区間が重複しない
test の組を列挙する純粋関数を提供する。 入力の読み込みや出力先の決定は
呼び出し側 (experiments/jsperf/pair/**) に閉じる。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations

from scipy import stats

__all__ = ["mean_confidence_interval", "disjoint_interval_pairs"]


def mean_confidence_interval(samples: Sequence[float], confidence: float = 0.95) -> tuple[float, float, float]:
    """標本平均と、その平均に対する t 分布ベースの信頼区間を返す.

    Args:
        samples: 計測サンプル列 (jsPerf では 1 ラウンドあたりの実行時間 ns)。
        confidence: 信頼水準 (0 < confidence < 1)。

    Returns:
        (平均, 信頼区間下限, 信頼区間上限)。 標本標準偏差が 0 のときは下限 = 上限 = 平均。

    Raises:
        ValueError: サンプル数が 2 未満、または confidence が範囲外のとき。
    """
    if len(samples) < 2:
        raise ValueError(f"samples must have at least 2 elements: {len(samples)}")
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"confidence must be in (0, 1): {confidence}")

    n = len(samples)
    mean = float(stats.tmean(samples))
    sem = float(stats.sem(samples))
    if sem == 0.0:
        return mean, mean, mean
    half_width = float(stats.t.ppf(0.5 + confidence / 2.0, n - 1)) * sem
    return mean, mean - half_width, mean + half_width


def disjoint_interval_pairs(intervals: Mapping[int, tuple[float, float]]) -> list[tuple[int, int]]:
    """信頼区間が一切重複しない test の組を (下限が小さい方, 大きい方) の順で列挙する.

    Args:
        intervals: test_idx -> (信頼区間下限, 信頼区間上限)。

    Returns:
        重複なしと判定された (速い側 test_idx, 遅い側 test_idx) のリスト。
        test_idx の昇順ペアでソートされる。
    """
    pairs: list[tuple[int, int]] = []
    for a, b in combinations(sorted(intervals), 2):
        a_low, a_high = intervals[a]
        b_low, b_high = intervals[b]
        if a_high < b_low:
            pairs.append((a, b))
        elif b_high < a_low:
            pairs.append((b, a))
    return pairs
