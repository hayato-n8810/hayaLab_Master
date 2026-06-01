"""M0 — Ordered Hash 集約.

`docs/aggregate.md` §3 M0 に対応する完全一致集約．各ノードを
``(name, value, parent_name)`` のタプルに正規化し、Pattern 全体の
タプル列を順序付きで連結して SHA-256 を取る．**同じハッシュを持つ
Pattern 同士のみを集約**する（最も厳しい集約）．

設計上の選択:

* ``parent_name`` は ``parent_relative[-1]`` が指す origin_index のノードの
  ``name`` を採用する．これは同じ ``(name, value)`` でも親文脈が異なれば
  別物として扱うための階層判別力を与える．
* ノードが root（``parent_relative`` が空 / parent_relative[-1] が
  cutout 外）の場合 ``parent_name = "__ROOT__"`` を採用する．
* punctuation は抽象化前段で除外済みなので、追加のフィルタは入れない．

集約鍵となる canonical 文字列の形式は次の通り（ノードを ``|`` で連結）::

    "<name>::<value>::<parent_name>|<name>::<value>::<parent_name>|..."

計算量: $O(N \\cdot n)$（$n$ は平均ノード数, $N$ は Pattern 数）．
ハッシュ計算のみで、ペアごとの比較は不要．
"""

from __future__ import annotations

import logging
from collections import defaultdict

from ast_node import Pattern
from cluster import make_class_id_from_content
from parallel import compute_keys_parallel

logger = logging.getLogger(__name__)

ROOT_PARENT_NAME = "__ROOT__"


def canonical_key(pattern: Pattern) -> str:
    """Public alias of :func:`_canonical_key` for parallel worker dispatch."""
    return _canonical_key(pattern)


def _canonical_key(pattern: Pattern) -> str:
    """Build the canonical ordered hash key for ``pattern``.

    Each TemplateNode contributes ``"{name}::{value}::{parent_name}"``,
    joined by ``|`` in original (origin_index order from the cutout).
    """
    nodes = pattern.ast_template
    index_to_name = {n.origin_index: n.name for n in nodes}
    parts: list[str] = []
    for n in nodes:
        if n.parent_relative:
            p_last = n.parent_relative[-1]
            parent_name = index_to_name.get(p_last, ROOT_PARENT_NAME)
        else:
            parent_name = ROOT_PARENT_NAME
        value = n.value if n.value is not None else ""
        parts.append(f"{n.name}::{value}::{parent_name}")
    return "|".join(parts)


def cluster_m0(patterns: list[Pattern], workers: int = 1) -> dict[str, list[str]]:
    """Cluster patterns by ordered-hash exact match.

    Args:
        patterns: list of :class:`Pattern` at the same abstraction level.
        workers: parallel worker count (>=2 enables mb_id-chunked parallel
            key computation).  Output is unchanged regardless of value.

    Returns:
        ``{class_id: sorted member cutout_ids}`` dict.
    """
    if not patterns:
        return {}

    level = patterns[0].abst_level
    buckets = compute_keys_parallel(
        patterns,
        key_fn_module="methods.m0_ordered_hash",
        key_fn_name="canonical_key",
        workers=workers,
    )

    result: dict[str, list[str]] = {}
    for key, members in sorted(buckets.items(), key=lambda kv: sorted(kv[1])):
        members_sorted = sorted(members)
        class_id = make_class_id_from_content(level, "M0", key)
        result[class_id] = members_sorted

    logger.debug(
        "M0 ordered-hash at level %d: %d patterns → %d classes",
        level,
        len(patterns),
        len(result),
    )
    return result
