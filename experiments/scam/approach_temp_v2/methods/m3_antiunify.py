"""M3 — Anti-unification (LGG) 集約.

approach_temp/methods/m3_antiunify.py の逐次版を v2 に移植し、ペア sim
計算の chunk 並列化を追加した版．

文献基盤: LASE\\cite{meng2013lase}, Refazer\\cite{rolim2017refazer},
Getafix\\cite{bader2019getafix}．

集約規則 (sim, lgg) は approach_temp と同一．**並列経路は逐次経路と
bit-identical な candidates list を生成する**ことが保証される：

* ペア (i, j) (i < j) ごとの sim 計算は独立かつ決定的
* chunk worker は ``(i_start, i_end)`` を受け取り、その範囲の i から j > i の
  ペアを計算
* メイン側で chunk 結果を ``i_start`` 順にソートしてから結合 → 逐次経路の
  二重 for ループと同じペア順序が再現される
* candidates list を決定的タイブレーク (sim 降順、同 sim では pair hash) で
  ソートして greedy Union-Find merge → workers の値によらず同一クラス分割

つまり ``workers >= 2`` を指定しても ``workers = 1`` と同じ出力が得られる
（approach_temp の M3 並列化と同じ保証）．

Worker init は pickle ファイル経由で TreeNode を 1 度だけ構築する．これは
``spawn`` start method (macOS/Windows) でも安全に動作する設計．
"""

from __future__ import annotations

import hashlib
import logging
import pickle
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from ast_node import Pattern, TreeNode
from cluster import UnionFind, make_class_id_from_content, nodes_to_tree

logger = logging.getLogger(__name__)

SLOT_NAME = "__slot__"


def _slot_node() -> TreeNode:
    return TreeNode(name=SLOT_NAME, value=None, is_slot=True)


def _lcs_pairs(a_children: list[TreeNode], b_children: list[TreeNode]) -> list[tuple[int, int]]:
    m, n = len(a_children), len(b_children)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a_children[i - 1].name == b_children[j - 1].name:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    pairs: list[tuple[int, int]] = []
    i, j = m, n
    while i > 0 and j > 0:
        if a_children[i - 1].name == b_children[j - 1].name and dp[i][j] == dp[i - 1][j - 1] + 1:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def lgg(a: TreeNode, b: TreeNode) -> TreeNode:
    """Least General Generalization of two ordered trees."""
    if a.name != b.name:
        return _slot_node()

    merged_value: str | None
    if a.value is None or b.value is None:
        merged_value = None
    elif a.value == b.value:
        merged_value = a.value
    else:
        merged_value = None

    merged_children: list[TreeNode] = []
    if not a.children and not b.children:
        pass
    elif not a.children or not b.children:
        max_children = max(len(a.children), len(b.children))
        merged_children = [_slot_node() for _ in range(max_children)]
    else:
        pairs = _lcs_pairs(a.children, b.children)
        used_b = {j for _, j in pairs}
        b_before: list[list[int]] = [[] for _ in range(len(a.children) + 1)]
        prev_bi = -1
        for ai, bi in pairs:
            for bj in range(prev_bi + 1, bi):
                if bj not in used_b:
                    b_before[ai].append(bj)
            prev_bi = bi
        last_bi = pairs[-1][1] if pairs else -1
        trailing_b = [bj for bj in range(last_bi + 1, len(b.children)) if bj not in used_b]
        pair_map = dict(pairs)
        for ai, a_child in enumerate(a.children):
            for _bj in b_before[ai]:
                merged_children.append(_slot_node())
            if ai in pair_map:
                bj = pair_map[ai]
                merged_children.append(lgg(a_child, b.children[bj]))
            else:
                merged_children.append(_slot_node())
        for _ in trailing_b:
            merged_children.append(_slot_node())

    return TreeNode(
        name=a.name,
        value=merged_value,
        children=merged_children,
        variadic=a.variadic or b.variadic,
    )


def sim(a: TreeNode, b: TreeNode) -> float:
    """sim(A, B) = |non_slot(lgg(A, B))| / (|A| + |B| - |lgg(A, B)|)."""
    g = lgg(a, b)
    denom = a.size() + b.size() - g.size()
    if denom <= 0:
        return 1.0
    return g.non_slot_size() / denom


def is_degenerate(lgg_tree: TreeNode, initial_size: int, rho: float) -> bool:
    if initial_size == 0:
        return False
    return lgg_tree.non_slot_size() < rho * initial_size


# ---------------------------------------------------------------------------
# Parallel candidate computation (workers > 1)
# ---------------------------------------------------------------------------

# Worker-global state populated by :func:`_worker_init`.
_W_IDS: list[str] = []
_W_TREES: dict[str, TreeNode] = {}
_W_SIZES: dict[str, int] = {}


def _worker_init(pickle_path: str) -> None:
    """ProcessPoolExecutor initializer: load patterns and build trees.

    A pickle file holding the Pattern list is loaded once per worker; each
    worker builds its own TreeNode dict in memory.  Chunk tasks then pass
    only ``(i_start, i_end)`` so large state isn't re-pickled per call.
    """
    global _W_IDS, _W_TREES, _W_SIZES
    with open(pickle_path, "rb") as f:
        patterns = pickle.load(f)
    _W_IDS = [p.cutout_id for p in patterns]
    _W_TREES = {p.cutout_id: nodes_to_tree(p.ast_template) for p in patterns}
    _W_SIZES = {cid: t.size() for cid, t in _W_TREES.items()}


def _compute_pair_candidates_chunk(
    i_start: int,
    i_end: int,
    tau_sim: float,
    kappa: float,
) -> list[tuple[float, str, str]]:
    """Compute sim for pairs (i, j) where i ∈ [i_start, i_end), j > i.

    Pairs are emitted in the same order as the sequential nested for-loop,
    so concatenating chunk results by ``i_start`` reproduces the sequential
    ``candidates`` list exactly.
    """
    candidates: list[tuple[float, str, str]] = []
    n = len(_W_IDS)
    for i in range(i_start, min(i_end, n)):
        a_id = _W_IDS[i]
        sa = _W_SIZES[a_id]
        if sa == 0:
            continue
        ta = _W_TREES[a_id]
        for j in range(i + 1, n):
            b_id = _W_IDS[j]
            sb = _W_SIZES[b_id]
            if sb == 0:
                continue
            ratio = max(sa, sb) / min(sa, sb)
            if ratio > kappa:
                continue
            s = sim(ta, _W_TREES[b_id])
            if s >= tau_sim:
                candidates.append((s, a_id, b_id))
    return candidates


def _make_chunks(n: int, target_chunks: int) -> list[tuple[int, int]]:
    """Split [0, n) into roughly equal half-open ranges."""
    if target_chunks <= 1 or n <= target_chunks:
        return [(0, n)]
    step = (n + target_chunks - 1) // target_chunks
    return [(i, min(i + step, n)) for i in range(0, n, step)]


# ---------------------------------------------------------------------------
# cluster_m3 main entry
# ---------------------------------------------------------------------------


def cluster_m3(
    patterns: list[Pattern],
    tau_sim: float = 0.5,
    kappa: float = 3.0,
    rho: float = 0.5,
    workers: int = 1,
) -> dict[str, list[str]]:
    """Cluster patterns via greedy LGG anti-unification.

    Args:
        patterns: list of Pattern at the same level.
        tau_sim: minimum similarity for merge (LASE/approach_temp 経験値 0.5).
        kappa: maximum size ratio (max/min) allowed for merge.
        rho: minimum non-slot ratio to reject degenerate LGG.
        workers: number of parallel worker processes for pair candidate
            computation.  ``<=1`` runs sequentially (default).  The greedy
            Union-Find merge is always sequential to preserve determinism.

    Returns:
        ``{class_id: sorted members}`` dict.  Output is identical regardless
        of ``workers`` value.
    """
    if not patterns:
        return {}

    level = patterns[0].abst_level
    all_ids = [p.cutout_id for p in patterns]
    trees = {p.cutout_id: nodes_to_tree(p.ast_template) for p in patterns}
    sizes = {cid: t.size() for cid, t in trees.items()}

    candidates: list[tuple[float, str, str]] = []
    n = len(all_ids)

    if workers <= 1 or n < workers * 2:
        # Sequential candidate generation
        for i in range(n):
            a_id = all_ids[i]
            sa = sizes[a_id]
            if sa == 0:
                continue
            for j in range(i + 1, n):
                b_id = all_ids[j]
                sb = sizes[b_id]
                if sb == 0:
                    continue
                ratio = max(sa, sb) / min(sa, sb)
                if ratio > kappa:
                    continue
                s = sim(trees[a_id], trees[b_id])
                if s >= tau_sim:
                    candidates.append((s, a_id, b_id))
    else:
        # Parallel candidate generation: identical output to sequential
        # because chunk results are merged in `i_start` order.
        with tempfile.NamedTemporaryFile(suffix=".pkl", prefix=f"_m3_v2_L{level}_", delete=False) as tf:
            pkl_path = tf.name
            pickle.dump(patterns, tf, protocol=pickle.HIGHEST_PROTOCOL)
        try:
            target_chunks = max(workers * 4, 1)
            chunks = _make_chunks(n, target_chunks)
            chunk_results: list[tuple[int, list[tuple[float, str, str]]]] = []
            with ProcessPoolExecutor(
                max_workers=workers,
                initializer=_worker_init,
                initargs=(pkl_path,),
            ) as ex:
                futures = {ex.submit(_compute_pair_candidates_chunk, i0, i1, tau_sim, kappa): i0 for i0, i1 in chunks}
                for fut in as_completed(futures):
                    chunk_results.append((futures[fut], fut.result()))
            # Concatenate in i_start order — bit-identical to sequential
            chunk_results.sort(key=lambda x: x[0])
            for _, cand in chunk_results:
                candidates.extend(cand)
            logger.info(
                "M3 L%d parallel: %d chunks × %d workers → %d candidates",
                level,
                len(chunks),
                workers,
                len(candidates),
            )
        finally:
            Path(pkl_path).unlink(missing_ok=True)

    def _pair_hash(a: str, b: str) -> str:
        return hashlib.sha256("::".join(sorted((a, b))).encode("utf-8")).hexdigest()

    candidates.sort(key=lambda x: (-x[0], _pair_hash(x[1], x[2])))

    uf = UnionFind(all_ids)
    component_lgg: dict[str, TreeNode] = {cid: trees[cid] for cid in all_ids}
    component_init_size: dict[str, int] = {cid: sizes[cid] for cid in all_ids}

    for _, a, b in candidates:
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            continue
        merged = lgg(component_lgg[ra], component_lgg[rb])
        init_size = component_init_size[ra]
        if is_degenerate(merged, init_size, rho):
            continue
        uf.union(a, b)
        new_root = uf.find(a)
        component_lgg[new_root] = merged
        component_init_size[new_root] = init_size

    classes = uf.components()
    result: dict[str, list[str]] = {}
    representatives: dict[str, TreeNode] = {}
    for _root, members in sorted(classes.items(), key=lambda x: sorted(x[1])):
        members_sorted = sorted(members)
        class_id = make_class_id_from_content(level, "M3", ",".join(members_sorted))
        result[class_id] = members_sorted
        representatives[class_id] = component_lgg[_root]

    # Attach representative trees for export consumers
    cluster_m3.last_representatives = representatives  # type: ignore[attr-defined]

    logger.debug(
        "M3 LGG (tau=%.2f, kappa=%.1f, rho=%.2f) at level %d: %d → %d classes",
        tau_sim,
        kappa,
        rho,
        level,
        len(patterns),
        len(result),
    )
    return result
