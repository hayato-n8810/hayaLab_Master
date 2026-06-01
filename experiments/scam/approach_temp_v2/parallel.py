"""Pattern 単位の並列化ヘルパー (mb_id 単位の chunk 分割).

対象は exact-mode の fingerprint 計算 (M0/M1/M2 の集約鍵生成)．これらは
Pattern ごとに独立かつ決定的なため、Pattern 列を分割して並列計算しても
出力 dict は逐次実行と同一になることが保証される．

並列化しない手法:

* M1 ``jaccard``, M2 ``jaccard``: 全ペア Jaccard 比較 + Union-Find 貪欲併合．
  ペア計算順序が決定的タイブレーク (pair hash) で保たれているため理論的には
  並列化可能だが、本実装ではシンプル化のため逐次のまま．
* M3 LGG: 同様に並列化可能だが、approach_temp 側で実装済みのため v2 では
  逐次のみ提供．

Args design: ``workers <= 1`` のとき内部で逐次実行に fallback するため、
呼び出し側は常に `compute_keys_parallel` を呼んで構わない．
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from typing import Callable

from ast_node import Pattern

logger = logging.getLogger(__name__)


def _chunk_indices(n: int, n_chunks: int) -> list[tuple[int, int]]:
    """Split [0, n) into ``n_chunks`` roughly equal half-open ranges."""
    if n_chunks <= 1 or n <= n_chunks:
        return [(0, n)]
    step = (n + n_chunks - 1) // n_chunks
    return [(i, min(i + step, n)) for i in range(0, n, step)]


def _worker_compute_keys(args: tuple) -> list[tuple[str, str]]:
    """Worker entry: returns ``[(cutout_id, key), ...]`` for one chunk.

    ``key_fn`` is passed by qualified name so the worker re-imports it.
    ``key_fn_kwargs`` is a picklable dict of primitive args forwarded to the
    function call.  This pattern avoids inheriting module-level globals (which
    would break under the ``spawn`` start method on macOS / Windows).
    """
    patterns_chunk, key_fn_module, key_fn_name, key_fn_kwargs = args
    import importlib

    mod = importlib.import_module(key_fn_module)
    fn = getattr(mod, key_fn_name)
    return [(p.cutout_id, fn(p, **key_fn_kwargs)) for p in patterns_chunk]


def compute_keys_parallel(
    patterns: list[Pattern],
    key_fn_module: str,
    key_fn_name: str,
    workers: int = 1,
    key_fn_kwargs: dict | None = None,
) -> dict[str, list[str]]:
    """Compute per-Pattern keys (in parallel if ``workers > 1``) and bucket.

    Args:
        patterns: list of Pattern to bucket.
        key_fn_module: module name where ``key_fn`` lives (e.g.
            ``"methods.m0_ordered_hash"``).
        key_fn_name: function name; the function must take ``(pattern,
            **key_fn_kwargs)`` and return a hashable str key.  It must be a
            top-level callable so it pickles under ``spawn``.
        workers: number of worker processes (``<=1`` falls back to sequential).
        key_fn_kwargs: primitive-typed kwargs forwarded to every key_fn call.

    Returns:
        ``{key: sorted member cutout_ids}`` dict.  Equivalent (key-for-key)
        to a sequential bucket — determinism is preserved regardless of
        worker count.
    """
    if not patterns:
        return {}

    kwargs = dict(key_fn_kwargs or {})

    if workers <= 1 or len(patterns) < workers * 2:
        import importlib

        mod = importlib.import_module(key_fn_module)
        fn = getattr(mod, key_fn_name)
        buckets: dict[str, list[str]] = defaultdict(list)
        for p in patterns:
            buckets[fn(p, **kwargs)].append(p.cutout_id)
        return {k: sorted(v) for k, v in buckets.items()}

    chunks = _chunk_indices(len(patterns), workers)
    chunk_args = [(patterns[s:e], key_fn_module, key_fn_name, kwargs) for s, e in chunks]
    logger.info(
        "  parallel keys: %d patterns × %d chunks × %d workers (%s.%s)",
        len(patterns),
        len(chunks),
        workers,
        key_fn_module,
        key_fn_name,
    )
    buckets = defaultdict(list)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for partial in ex.map(_worker_compute_keys, chunk_args):
            for cutout_id, key in partial:
                buckets[key].append(cutout_id)
    return {k: sorted(v) for k, v in buckets.items()}
