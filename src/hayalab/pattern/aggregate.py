"""パターン抽出パイプライン Stage 4: 同値類集約。

Jaccard 閾値 τ で「データセットに対する検出結果」をベースにパターン間の同値判定を行い、
union-find で同値類を構築する。τ = 1.0 のときは検出結果完全一致による同値類化。
τ < 1.0 では推移性が崩れるため単連結クラスタリング（同値関係ではなく相互類似クラスタ）
として扱う。

各同値類は ClassMember (mb_id, signature, depth) のリストで「どのパターン (signature)
がどの MB から由来したか」を保持する。同一 signature が複数 MB から生成されるケースを
扱えるよう、(mb_id, signature, depth) のタプルで重複排除する。

公開 API:
    - aggregate_equivalence_classes(patterns, detection_results, tau)
"""

from __future__ import annotations

import hashlib

from hayalab.classes.pattern import ClassMember, EquivalenceClass, Pattern
from hayalab.config.pattern_config import DEFAULT_TAU


class _UnionFind:
    """連結成分管理用の簡易 union-find。"""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1


def aggregate_equivalence_classes(
    patterns: list[Pattern],
    detection_results: dict[str, set[int]],
    tau: float = DEFAULT_TAU,
) -> list[EquivalenceClass]:
    """パターン集合から同値類を構築する。

    Args:
        patterns: 全候補パターン。
        detection_results: パターン同一性判定用ハッシュ (Pattern.signature) -> 検出結果
            （マッチした MB id 集合）のマッピング。
        tau: Jaccard 閾値（デフォルト 1.0 = 完全一致）。

    Returns:
        同値類のリスト（class_id 昇順）。各クラスは ClassMember のリストとして
        メンバ（由来 MB × signature × depth）を保持する。
    """
    # signature 単位で union-find を実行する（同一 signature のパターンは検出結果も同一）
    hashes = sorted({p.signature for p in patterns if p.signature})
    n = len(hashes)

    # 検出結果が一致（または Jaccard >= τ）のパターン同士を union
    uf = _UnionFind(n)
    for i in range(n):
        det_i = detection_results.get(hashes[i], set())
        for j in range(i + 1, n):
            det_j = detection_results.get(hashes[j], set())
            if tau >= 1.0:
                if det_i == det_j:
                    uf.union(i, j)
            else:
                # Jaccard 類似度（両方空なら 0.0）
                union = det_i | det_j
                jaccard = len(det_i & det_j) / len(union) if union else 0.0
                if jaccard >= tau:
                    uf.union(i, j)

    # signature → そのハッシュを共有するパターン群 のマップ
    sig_to_patterns: dict[str, list[Pattern]] = {}
    for p in patterns:
        if p.signature:
            sig_to_patterns.setdefault(p.signature, []).append(p)

    # ルート別にメンバハッシュを集約
    root_to_hashes: dict[int, list[str]] = {}
    for i, h in enumerate(hashes):
        root_to_hashes.setdefault(uf.find(i), []).append(h)

    classes: list[EquivalenceClass] = []
    for member_hashes in root_to_hashes.values():
        member_hashes_sorted = sorted(member_hashes)

        # 同値類の検出結果は union（τ=1.0 なら全員同一）
        merged_detection: set[int] = set()
        for h in member_hashes_sorted:
            merged_detection |= detection_results.get(h, set())

        # (mb_id, signature, depth) のタプルで重複排除しつつ ClassMember を構築
        member_keys: set[tuple[int, str, int]] = set()
        for h in member_hashes_sorted:
            for p in sig_to_patterns.get(h, []):
                member_keys.add((p.mb_id, p.signature, p.depth))
        members = [ClassMember(mb_id=mb_id, signature=sig, depth=depth) for mb_id, sig, depth in sorted(member_keys)]

        # 同値類識別ハッシュ: メンバハッシュ列を結合したものから決定論的に算出
        class_id = hashlib.sha256(",".join(member_hashes_sorted).encode("utf-8")).hexdigest()[:16]

        classes.append(
            EquivalenceClass(
                class_id=class_id,
                members=members,
                detect_id=merged_detection,
            )
        )

    classes.sort(key=lambda c: c.class_id)
    return classes
