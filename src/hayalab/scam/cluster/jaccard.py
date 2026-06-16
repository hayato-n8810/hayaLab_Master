"""集合演算と Union-Find、 features cache スキーマ定数 / 鮮度判定。

scam の bigram cache pickle スキーマも当モジュールに集約する（producer は
experiments 側の cache I/O、 consumer は Representative_value の戦略スクリプト群）。
"""

from __future__ import annotations

from pathlib import Path

# scam features cache pickle のスキーマ識別子（producer と consumer で共有）。
NGRAMS_CACHE_VERSION = 2
NGRAMS_CACHE_SCHEMA = "abst_id_to_features_v2"


def is_cache_fresh(cache_path: Path, source_path: Path) -> bool:
    """``cache_path`` が存在し ``source_path`` 以降の mtime ならば ``True``。

    どちらかが欠けていれば ``False``。 source 不在のときは「鮮度判定不能だが
    cache あり」として ``True`` を返す（experiments 側 cache 読み込みでの fallback 制御に使う）。
    """
    if not cache_path.exists():
        return False
    if not source_path.exists():
        return True
    return cache_path.stat().st_mtime >= source_path.stat().st_mtime


def jaccard(a: frozenset, b: frozenset) -> float:
    """Frozenset の Jaccard 係数（両者空のとき 1.0、片方空のとき 0.0）。

    Args:
        a: 集合 1。
        b: 集合 2。

    Returns:
        ``|a ∩ b| / |a ∪ b|``。 両者空のときは ``1.0``、 union が 0 のときは ``0.0``。
    """
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a) + len(b) - inter
    return inter / union if union else 0.0


def member_to_mb_id(member: str) -> int:
    """cutout_id ``"{mb_id}_{depth}"`` → ``mb_id``（int）。"""
    mb_id_str, _depth = member.rsplit("_", 1)
    return int(mb_id_str)


class UnionFind:
    """文字列 ID 上の Union-Find（経路圧縮 + ランク併合）。"""

    def __init__(self, elements: list[str]) -> None:
        self._parent: dict[str, str] = {e: e for e in elements}
        self._rank: dict[str, int] = {e: 0 for e in elements}

    def find(self, x: str) -> str:
        """``x`` の属する集合の代表元を返す（経路圧縮あり）。"""
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: str, y: str) -> None:
        """``x`` と ``y`` の属する集合を併合する。"""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def components(self) -> dict[str, list[str]]:
        """``{root: sorted members}`` を決定的順序で返す。"""
        groups: dict[str, list[str]] = {}
        for e in self._parent:
            groups.setdefault(self.find(e), []).append(e)
        return {root: sorted(members) for root, members in sorted(groups.items())}
