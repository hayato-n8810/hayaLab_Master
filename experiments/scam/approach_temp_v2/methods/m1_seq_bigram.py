"""M1 — Sequence Bigram Fingerprint 集約.

`docs/aggregate.md` §3 M1 に対応．Pattern の TemplateNode 列を線形列として
扱い、隣接ペア ``(node_i, node_{i+1})`` の bigram fingerprint で比較する．

トークン化規約:

* 各 TemplateNode を **``(name, value)`` の 2 要素タプル** に縮約する．
  ``parent_name`` 等の補助情報は集約鍵に含めない．
* value は **slot タイプのみに正規化** する: ``$v0`` / ``$v1`` / ... → ``$v``
  （番号を捨てる）．対象は ``v`` / ``f`` / ``k`` / ``n`` / ``s`` の 5 prefix．
  ``$api`` は既に番号なしのためそのまま．
  これによりスロット番号の偶然差（同 cutout 内での変数登場順差など）を吸収する．
* **``variadic=True`` の TemplateNode は集約鍵から除外** する．
  L2 で導入される ``function_like`` / ``var_decl_stmt`` / ``var_decl_kw`` などの
  非終端は子要素 arity が揺らぐため、`aggregate.md` §3 M3 が意図する
  "variadic ノードは子要素揺らぎを吸収する" を bigram 系で実現する近似として、
  variadic ノード自体を bigram 系列から外す．子サブツリーは含む．

二種類の集約モード:

* ``mode="exact"``: 全 bigram と出現位置が完全一致する Pattern 同士のみ集約．
* ``mode="jaccard"``: 共通 bigram 数 / 和集合 bigram 数 を Jaccard 類似度として
  測り、閾値 ``tau_jaccard`` 以上のペアを Union-Find で貪欲併合．
  SourcererCC 等で標準の 0.7 を本研究のデフォルトとする．

計算量:

* exact mode: $O(N \\cdot n)$
* jaccard mode: $O(N^2 \\cdot n)$
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import re
import tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from ast_node import Pattern, TemplateNode
from cluster import UnionFind, make_class_id_from_content
from parallel import compute_keys_parallel

logger = logging.getLogger(__name__)


# Slot 番号正規化: ``$v0`` → ``$v`` のように、prefix v/f/k/n/s に続く数字を捨てる．
# ``$api`` は既に番号なしなので別パスで素通しする．
_SLOT_NUM_RE = re.compile(r"^\$([vfkns])\d+$")


def normalize_value(value: str | None) -> str:
    """slot 番号を捨てて slot タイプのみに正規化する.

    * ``$v0``, ``$v17`` → ``$v``
    * ``$f0`` → ``$f``
    * ``$k0`` → ``$k``
    * ``$n0`` → ``$n``
    * ``$s0`` → ``$s``
    * ``$api`` → ``$api``  (既に番号なし)
    * その他の具体値はそのまま
    * ``None`` は空文字列に
    """
    if value is None:
        return ""
    m = _SLOT_NUM_RE.match(value)
    if m:
        return f"${m.group(1)}"
    return value


def _node_token(n: TemplateNode) -> tuple[str, str]:
    """Canonical (name, normalized_value) tuple."""
    return (n.name, normalize_value(n.value))


def _filtered_nodes(pattern: Pattern) -> list[TemplateNode]:
    """``variadic=True`` の TemplateNode を集約鍵から除外したノード列."""
    return [n for n in pattern.ast_template if not n.variadic]


def fingerprint_key(pattern: Pattern) -> str:
    """Top-level picklable key function for parallel dispatch.

    トークン化規約はモジュール docstring の通り (name, normalized_value のみ,
    variadic ノード除外, slot タイプ正規化)．補助引数は持たない．
    """
    return _fingerprint_hash(_bigrams(pattern))


def _bigrams(pattern: Pattern) -> list[tuple]:
    """Build the ordered bigram list of a Pattern.

    variadic=True のノードを除外したうえで隣接トークンペアを生成する．
    """
    nodes = _filtered_nodes(pattern)
    if len(nodes) < 2:
        return []
    tokens = [_node_token(n) for n in nodes]
    return list(zip(tokens[:-1], tokens[1:]))


def _fingerprint_hash(bigrams: list[tuple]) -> str:
    """SHA-256 of the position-aware bigram fingerprint."""
    parts: list[str] = []
    for i, bg in enumerate(bigrams):
        a, b = bg
        parts.append(f"{i}|{a}->{b}")
    return hashlib.sha256("/".join(parts).encode("utf-8")).hexdigest()


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Parallel jaccard pair computation
# ---------------------------------------------------------------------------

_W_IDS: list[str] = []
_W_SETS: dict[str, frozenset] = {}


def _worker_init_jaccard(pickle_path: str) -> None:
    """ProcessPoolExecutor initializer: load (ids, sets) for pair computation."""
    global _W_IDS, _W_SETS
    with open(pickle_path, "rb") as f:
        _W_IDS, _W_SETS = pickle.load(f)


def _compute_jaccard_chunk(
    i_start: int,
    i_end: int,
    tau_jaccard: float,
) -> list[tuple[float, str, str]]:
    """Compute Jaccard for pairs (i, j) where i ∈ [i_start, i_end), j > i.

    Same emission order as the sequential nested for-loop, so concatenating
    chunk results by ``i_start`` reproduces the sequential ``candidates`` list.
    """
    candidates: list[tuple[float, str, str]] = []
    n = len(_W_IDS)
    for i in range(i_start, min(i_end, n)):
        a_id = _W_IDS[i]
        a_set = _W_SETS[a_id]
        for j in range(i + 1, n):
            b_id = _W_IDS[j]
            b_set = _W_SETS[b_id]
            if not a_set and not b_set:
                s = 1.0
            else:
                inter = len(a_set & b_set)
                union = len(a_set | b_set)
                s = inter / union if union else 0.0
            if s >= tau_jaccard:
                candidates.append((s, a_id, b_id))
    return candidates


def _make_chunks(n: int, target_chunks: int) -> list[tuple[int, int]]:
    if target_chunks <= 1 or n <= target_chunks:
        return [(0, n)]
    step = (n + target_chunks - 1) // target_chunks
    return [(i, min(i + step, n)) for i in range(0, n, step)]


def cluster_m1(
    patterns: list[Pattern],
    mode: str = "exact",
    tau_jaccard: float = 0.7,
    workers: int = 1,
) -> dict[str, list[str]]:
    """Cluster patterns via sequence bigram fingerprint.

    Args:
        patterns: list of :class:`Pattern` at the same level.
        mode: ``"exact"`` (position-aware bigram completeness) or
            ``"jaccard"`` (bigram set Jaccard ≥ tau_jaccard).
        tau_jaccard: similarity threshold for jaccard mode
            (SourcererCC 標準 0.7).
        workers: parallel worker count for exact mode.

    Returns:
        ``{class_id: sorted member cutout_ids}``.
    """
    if not patterns:
        return {}

    level = patterns[0].abst_level

    if mode == "exact":
        buckets = compute_keys_parallel(
            patterns,
            key_fn_module="methods.m1_seq_bigram",
            key_fn_name="fingerprint_key",
            workers=workers,
        )
        result: dict[str, list[str]] = {}
        for key, members in sorted(buckets.items(), key=lambda kv: sorted(kv[1])):
            members_sorted = sorted(members)
            class_id = make_class_id_from_content(level, "M1", key)
            result[class_id] = members_sorted
        logger.debug(
            "M1 (exact) at level %d: %d patterns → %d classes",
            level,
            len(patterns),
            len(result),
        )
        return result

    if mode == "jaccard":
        sets: dict[str, frozenset] = {}
        ids: list[str] = []
        for p in patterns:
            bg = _bigrams(p)
            sets[p.cutout_id] = frozenset(bg)
            ids.append(p.cutout_id)

        n = len(ids)
        candidates: list[tuple[float, str, str]] = []

        if workers <= 1 or n < workers * 2:
            # Sequential pair computation
            for i in range(n):
                a_set = sets[ids[i]]
                for j in range(i + 1, n):
                    b_set = sets[ids[j]]
                    if not a_set and not b_set:
                        s = 1.0
                    else:
                        inter = len(a_set & b_set)
                        union = len(a_set | b_set)
                        s = inter / union if union else 0.0
                    if s >= tau_jaccard:
                        candidates.append((s, ids[i], ids[j]))
        else:
            # Parallel pair computation: identical output because chunks are
            # merged in i_start order (same emission order as the sequential
            # nested for-loop).
            with tempfile.NamedTemporaryFile(suffix=".pkl", prefix=f"_m1_jac_L{level}_", delete=False) as tf:
                pkl_path = tf.name
                pickle.dump((ids, sets), tf, protocol=pickle.HIGHEST_PROTOCOL)
            try:
                target_chunks = max(workers * 4, 1)
                chunks = _make_chunks(n, target_chunks)
                chunk_results: list[tuple[int, list[tuple[float, str, str]]]] = []
                with ProcessPoolExecutor(
                    max_workers=workers,
                    initializer=_worker_init_jaccard,
                    initargs=(pkl_path,),
                ) as ex:
                    futures = {ex.submit(_compute_jaccard_chunk, i0, i1, tau_jaccard): i0 for i0, i1 in chunks}
                    for fut in as_completed(futures):
                        chunk_results.append((futures[fut], fut.result()))
                chunk_results.sort(key=lambda x: x[0])
                for _, cand in chunk_results:
                    candidates.extend(cand)
                logger.info(
                    "M1 jaccard L%d parallel: %d chunks × %d workers → %d candidates",
                    level,
                    len(chunks),
                    workers,
                    len(candidates),
                )
            finally:
                Path(pkl_path).unlink(missing_ok=True)

        uf = UnionFind(ids)

        def _pair_hash(a: str, b: str) -> str:
            return hashlib.sha256("::".join(sorted((a, b))).encode("utf-8")).hexdigest()

        candidates.sort(key=lambda x: (-x[0], _pair_hash(x[1], x[2])))
        for _, a, b in candidates:
            uf.union(a, b)

        classes = uf.components()
        result = {}
        for _root, members in sorted(classes.items(), key=lambda x: sorted(x[1])):
            members_sorted = sorted(members)
            class_id = make_class_id_from_content(level, "M1", f"jaccard:{','.join(members_sorted)}")
            result[class_id] = members_sorted
        logger.debug(
            "M1 (jaccard tau=%.2f) at level %d: %d patterns → %d classes",
            tau_jaccard,
            level,
            len(patterns),
            len(result),
        )
        return result

    raise ValueError(f"Unsupported mode: {mode!r} (expected 'exact' or 'jaccard')")
