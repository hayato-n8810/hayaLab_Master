"""パターン抽出パイプライン Stage 5b: 抽象化レベル別の集約観測量。

抽象化レベル A0..A3 各々で同値類集約を行った結果について、同値類の総数・集約済み
同値類数（検出結果サイズが 2 以上のクラス数）・singleton 数・集約済みクラスに属する MB 数・
最大検出結果サイズ・A → A+1 で所属クラスが変わる MB 数（migration）を算出する。

スコアによる自動選定は行わず、観測量を可視化して結果駆動で推奨 A を選ぶ方針。

公開 API:
    - compute_abstraction_observations(equivalence_classes_by_level, mb_class_assignment)
"""

from __future__ import annotations

from hayalab.classes.pattern import AbstractionObservation, EquivalenceClass


def compute_abstraction_observations(
    equivalence_classes_by_level: dict[int, list[EquivalenceClass]],
    mb_class_assignment: dict[int, dict[int, str]],
) -> list[AbstractionObservation]:
    """各抽象化レベルの集約観測量を算出する。

    Args:
        equivalence_classes_by_level: 抽象化レベル -> 同値類リスト。
        mb_class_assignment: mb_id -> {abst_level: class_id} のマップ。
            migration の算出に使用。

    Returns:
        観測量のリスト（A0..A3 の順）。指定されたレベルのみを返す。
    """
    levels = sorted(equivalence_classes_by_level.keys())
    observations: list[AbstractionObservation] = []

    for idx, level in enumerate(levels):
        classes = equivalence_classes_by_level[level]
        n_classes = len(classes)
        n_aggregated = sum(1 for c in classes if len(c.detect_id) >= 2)
        n_just_match = sum(1 for c in classes if len(c.detect_id) <= 1)
        mb_in_aggregated_set: set[int] = set()
        max_class_size = 0
        for c in classes:
            size = len(c.detect_id)
            if size > max_class_size:
                max_class_size = size
            if size >= 2:
                mb_in_aggregated_set |= c.detect_id
        mb_in_aggregated = len(mb_in_aggregated_set)

        migration_to_next: int | None = None
        if idx + 1 < len(levels):
            next_level = levels[idx + 1]
            count = 0
            for assignment in mb_class_assignment.values():
                cur = assignment.get(level)
                nxt = assignment.get(next_level)
                if cur is not None and nxt is not None and cur != nxt:
                    count += 1
            migration_to_next = count

        observations.append(
            AbstractionObservation(
                abst_level=level,
                n_classes=n_classes,
                n_aggregated=n_aggregated,
                n_just_match=n_just_match,
                mb_in_aggregated=mb_in_aggregated,
                max_class_size=max_class_size,
                migration_to_next=migration_to_next,
            )
        )

    return observations
