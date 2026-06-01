"""M2 — N-gram 集約.

`docs/aggregate.md` §3 M2 を本研究のトークン化規約に合わせて再定義した版．
M1 (bigram) を任意の n に拡張した n-gram 集約．

トークン化規約は M1 と共通:

* 各 TemplateNode を **``(name, value)`` の 2 要素タプル** に縮約
* value は **slot タイプのみに正規化** (``$v0`` → ``$v`` など)
* **``variadic=True`` の TemplateNode は集約鍵から除外**

aggregate.md §3 M2 の原案は ``parent_path_hash`` を追加して階層情報を取り
込む設計だったが、本研究では M1 と統一したトークン化を採用したうえで n を
増やすことで近傍構造の情報量を制御する．n=2 で M1 と等価、n=3 以上で局所
文脈を広く拾う設計．

二種類の集約モード:

* ``mode="exact"``: 全 n-gram と出現位置が完全一致する Pattern 同士のみ集約
* ``mode="jaccard"``: n-gram set Jaccard ≥ tau_jaccard で貪欲併合
  （SourcererCC 標準の 0.7 を本研究のデフォルトとする）

計算量:

* exact mode: $O(N \\cdot n)$
* jaccard mode: $O(N^2 \\cdot n)$
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import tempfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from ast_node import Pattern, TemplateNode
from cluster import UnionFind, make_class_id_from_content
from parallel import compute_keys_parallel

# slot 番号正規化は M1 と共有
from methods.m1_seq_bigram import normalize_value

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parallel jaccard pair computation (M3 / M1 と同パターン)
# ---------------------------------------------------------------------------

_W_IDS: list[str] = []
_W_SETS: dict[str, frozenset] = {}


def _worker_init_jaccard(pickle_path: str) -> None:
    global _W_IDS, _W_SETS
    with open(pickle_path, "rb") as f:
        _W_IDS, _W_SETS = pickle.load(f)


def _compute_jaccard_chunk(
    i_start: int,
    i_end: int,
    tau_jaccard: float,
) -> list[tuple[float, str, str]]:
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


def fingerprint_key(pattern: Pattern, n_value: int = 2) -> str:
    """Top-level picklable key function for parallel dispatch."""
    tokens = _tokens(pattern)
    return _fingerprint_hash(_ngrams(tokens, n_value))


def _node_token(n: TemplateNode) -> tuple[str, str]:
    """Canonical (name, normalized_value) tuple — M1 と共通."""
    return (n.name, normalize_value(n.value))


def _tokens(pattern: Pattern) -> list[tuple[str, str]]:
    """Return token list, dropping variadic=True nodes.

    M1 と同じトークン化規約．M2 では「path 情報なしの (name, value) のみ」を
    使い、n-gram の n で文脈の広さを制御する設計とする．
    """
    return [_node_token(n) for n in pattern.ast_template if not n.variadic]


def _ngrams(tokens: list[tuple[str, str]], n: int) -> list[tuple]:
    """Return ordered list of n-grams (tuples of n tokens)."""
    if len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _fingerprint_hash(ngrams: list[tuple]) -> str:
    """SHA-256 of position-aware n-gram fingerprint."""
    parts: list[str] = []
    for i, ng in enumerate(ngrams):
        parts.append(f"{i}|" + "->".join(str(t) for t in ng))
    return hashlib.sha256("/".join(parts).encode("utf-8")).hexdigest()


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def cluster_m2(
    patterns: list[Pattern],
    n_value: int = 2,
    mode: str = "exact",
    tau_jaccard: float = 0.7,
    workers: int = 1,
) -> dict[str, list[str]]:
    """Cluster patterns via n-gram fingerprint with shared M1 tokenization.

    Args:
        patterns: list of :class:`Pattern` at the same level.
        n_value: n for n-gram (default 2 = bigram, 同じ token 化規約で M1 と等価;
            n=3 以上で局所構造を広く取り込む).
        mode: ``"exact"`` or ``"jaccard"``.
        tau_jaccard: similarity threshold for jaccard mode (SourcererCC 標準 0.7).
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
            key_fn_module="methods.m2_path_ngram",
            key_fn_name="fingerprint_key",
            workers=workers,
            key_fn_kwargs={"n_value": n_value},
        )
        result: dict[str, list[str]] = {}
        for key, members in sorted(buckets.items(), key=lambda kv: sorted(kv[1])):
            members_sorted = sorted(members)
            class_id = make_class_id_from_content(level, "M2", key)
            result[class_id] = members_sorted
        logger.debug(
            "M2 (exact n=%d) at level %d: %d patterns → %d classes",
            n_value,
            level,
            len(patterns),
            len(result),
        )
        return result

    if mode == "jaccard":
        sets: dict[str, frozenset] = {}
        ids: list[str] = []
        for p in patterns:
            tokens = _tokens(p)
            sets[p.cutout_id] = frozenset(_ngrams(tokens, n_value))
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
            # Parallel: chunks merged in i_start order — bit-identical output
            with tempfile.NamedTemporaryFile(suffix=".pkl", prefix=f"_m2_jac_L{level}_", delete=False) as tf:
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
                    "M2 jaccard L%d parallel: %d chunks × %d workers → %d candidates",
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
            class_id = make_class_id_from_content(level, "M2", f"jaccard:n{n_value}:{','.join(members_sorted)}")
            result[class_id] = members_sorted
        logger.debug(
            "M2 (jaccard n=%d tau=%.2f) at level %d: %d patterns → %d classes",
            n_value,
            tau_jaccard,
            level,
            len(patterns),
            len(result),
        )
        return result

    raise ValueError(f"Unsupported mode: {mode!r} (expected 'exact' or 'jaccard')")
