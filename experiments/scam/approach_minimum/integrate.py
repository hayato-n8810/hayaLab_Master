"""approach_minimum 統合: 三本立て (bigram Jaccard + singleton 完全一致 + empty 除外).

処理概要:

1. 入力 ``abstract_level{L}.json`` を読み込む。
2. Diff / Brother / ExParent / Parent の各 depth について、 cutout の有効
   トークン列 (``variadic=True`` を除外したノード列) の長さ ``n_t`` で振り分ける。

   * ``n_t == 0``           → 除外（クラスタ生成対象外）。 cutout は存在するが
     全ノードが variadic で抽象化後に有効トークンが残らないケース。
   * ``0 < n_t < n``        → singleton: token tuple 完全一致で grouping。
     既定 ``n=2`` のとき ``n_t == 1`` のみ該当。
   * ``n_t >= n``           → bigram: Jaccard 係数 ≥ tau で貪欲併合。

3. depth ごとに「bigram クラスタ」+「singleton クラスタ」を 1 つの ``classes``
   辞書に統合して JSON で書き出す。 ``class_id`` の prefix で由来を判別できる
   (``L*_M2_*``: bigram, ``L*_S1_*``: singleton)。

トークン化規約 (m2_path_ngram.py と共通):

* 各ノードを ``(name, normalize_value(value))`` の 2 要素タプルに縮約。
* value は slot タイプのみに正規化 (``$v0`` → ``$v`` 等、prefix v/f/k/n/s)。
  ``$api`` は番号なしのため素通し。
* ``variadic=True`` のノードは集約鍵から除外する（子サブツリーは含む）。

cutout_id は ``"{mb_id}_{depth}"`` 形式。 depth ごとに独立して併合するため、
クラスタのメンバーはこの cutout_id 文字列で表現される。

入力:
    outputs/scam/approach_minimum/abstract/abstract_level{0,1,2,3}.json

出力:
    (通常モード)   outputs/scam/approach_minimum/integrate/level{L}/{depth}.json
    (server モード) outputs/scam/approach_minimum/integrate/jaccard{NN}/level{L}/{depth}/{depth}.json

各出力 JSON のスキーマ::

    {
        "meta": {
            "level": int, "depth": str, "n": int, "tau": float,
            "mode": "jaccard+singleton",
            "num_bigram_patterns": int,
            "num_singleton_patterns": int,
            "num_excluded_empty": int,
            "num_bigram_classes": int,
            "num_singleton_classes": int,
            "num_classes": int,
        },
        "classes": {class_id: [cutout_id, ...], ...}
    }

class_id prefix:

* ``L{level}_M2_{hash8}``: bigram Jaccard 由来のクラスタ。
* ``L{level}_S1_{hash8}``: singleton 完全一致 由来のクラスタ。

Cache pickle (v2):
    outputs/scam/approach_minimum/abstract/bigrams_level{L}_n{N}.pkl
    {
        "version": 2,
        "schema": "abst_id_to_features_v2",
        "level": L,
        "n": N,
        "bigrams":    {depth: {mb_id: frozenset(bigrams)}},  # n_t >= n のみ
        "singletons": {depth: {mb_id: tuple(tokens)}},       # 0 < n_t < n のみ
        "excluded":   {depth: int},                          # n_t == 0 の件数
    }

実行例:
    uv run python experiments/scam/approach_minimum/integrate.py --workers 7
    uv run python experiments/scam/approach_minimum/integrate.py --levels 0 --n 2 --tau 0.7
    uv run python experiments/scam/approach_minimum/integrate.py --server --taus 0.5 0.7 0.9 --create-cache --workers 40
"""

from __future__ import annotations

import argparse
import logging
import os
import pickle
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path

import hayalab

logger = logging.getLogger(__name__)

# cutout depth の順序（出力スキーマ安定化のため固定）。
DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")

# リポジトリルート（experiments/scam/approach_minimum/integrate.py の 3 つ上）。
ROOT = Path(__file__).resolve().parents[3]

# Features cache のスキーマバージョン。v1 (旧 ``abst_id_to_ngrams``) からは
# bigram + singleton + excluded の三本立てに切り替わるため version を bump し、
# 互換性のない古い cache は自動的に invalid 扱いとなる。
NGRAMS_CACHE_VERSION = 2
NGRAMS_CACHE_SCHEMA = "abst_id_to_features_v2"

# slot 番号正規化: ``$v0`` → ``$v``。prefix v/f/k/n/s に続く数字を捨てる。
# ``$api`` は数字を持たないためマッチせず素通しになる。
_SLOT_NUM_RE = re.compile(r"^\$([vfkns])\d+$")


# ---------------------------------------------------------------------------
# Tokenization (m2_path_ngram.py と共通の規約)
# ---------------------------------------------------------------------------


def normalize_value(value: str | None) -> str:
    """Slot 番号を捨てて slot タイプのみに正規化する。

    Args:
        value: ノードの ``value`` 文字列（``None`` 可）。

    Returns:
        ``$v0`` → ``$v`` のように slot 番号を除いた値。具体値はそのまま、
        ``None`` は空文字列。
    """
    if value is None:
        return ""
    m = _SLOT_NUM_RE.match(value)
    if m:
        return f"${m.group(1)}"
    return value


def _node_token(node: dict) -> tuple[str, str]:
    """ノード dict を canonical な ``(name, normalized_value)`` タプルに縮約する。"""
    return (node["name"], normalize_value(node.get("value")))


def _tokens(nodes: list[dict]) -> list[tuple[str, str]]:
    """``variadic=True`` のノードを除外したトークン列を返す。"""
    return [_node_token(n) for n in nodes if not n.get("variadic", False)]


def _ngrams(tokens: list[tuple[str, str]], n: int) -> list[tuple]:
    """トークン列から n-gram（n 個連続トークンのタプル）の列を返す。"""
    if len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


# ---------------------------------------------------------------------------
# Union-Find / class_id 生成
# ---------------------------------------------------------------------------


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


def _content_hash(value: str) -> str:
    """SHA-256 の先頭 8 桁 hex。"""
    return sha256(value.encode("utf-8")).hexdigest()[:8]


def _make_class_id(level: int, content: str, prefix: str) -> str:
    """``L{level}_{prefix}_{hash8}`` 形式の class ID を生成する。

    Args:
        level: 抽象化レベル。
        content: ハッシュ元の文字列（生成戦略 + メンバー情報を含む）。
        prefix: 由来を示す短い識別子 (``M2``: bigram, ``S1``: singleton)。
    """
    return f"L{level}_{prefix}_{_content_hash(content)}"


def _pair_hash(a: str, b: str) -> str:
    """ペア ``(a, b)`` の順序非依存ハッシュ（候補ソートのタイブレーク用）。"""
    return sha256("::".join(sorted((a, b))).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Feature extraction (三本立て: bigram / singleton / excluded)
# ---------------------------------------------------------------------------


def _extract_features(
    records: list[dict],
    depths: tuple[str, ...],
    n_value: int,
) -> tuple[
    dict[str, dict[int, frozenset]],
    dict[str, dict[int, tuple[tuple[str, str], ...]]],
    dict[str, int],
]:
    """1 レベル分の records から features を 3 種に振り分ける。

    各 depth について、 cutout の有効トークン列長 ``n_t`` で分類する:

    * ``n_t == 0``           → ``excluded[depth]`` の件数に算入し、何も登録しない。
    * ``n_t >= n_value``     → ``bigrams[depth][mb_id]`` に bigram frozenset を格納。
    * ``0 < n_t < n_value``  → ``singletons[depth][mb_id]`` に token tuple を格納。

    Args:
        records: ``abstract_level{L}.json`` の読み込み結果。
        depths: 対象 depth 群。
        n_value: n-gram の n（既定 2）。

    Returns:
        ``(bigrams, singletons, excluded)``。 ``cutout`` 自体が存在しない
        ``(mb_id, depth)`` ペアはどのテーブルにも現れない（既存挙動と整合）。
    """
    bigrams: dict[str, dict[int, frozenset]] = {d: {} for d in depths}
    singletons: dict[str, dict[int, tuple[tuple[str, str], ...]]] = {d: {} for d in depths}
    excluded: dict[str, int] = {d: 0 for d in depths}

    for entry in records:
        mb_id = entry["id"]
        cutouts = entry.get("cutouts", {})
        for depth in depths:
            cutout = cutouts.get(depth)
            if not cutout:
                continue
            tokens = _tokens(cutout.get("nodes", []))
            n_t = len(tokens)
            if n_t == 0:
                excluded[depth] += 1
            elif n_t >= n_value:
                bigrams[depth][mb_id] = frozenset(_ngrams(tokens, n_value))
            else:
                singletons[depth][mb_id] = tuple(tokens)
    return bigrams, singletons, excluded


# ---------------------------------------------------------------------------
# Cache I/O (v2 schema)
# ---------------------------------------------------------------------------


def _features_cache_path(input_dir: Path, level: int, n_value: int) -> Path:
    """Features cache pickle のパスを返す。

    パス名は v1 と同じ ``bigrams_level{L}_n{N}.pkl`` を維持するが、 schema は v2。
    旧 cache を読もうとした場合は version mismatch で再生成される。
    """
    return input_dir / f"bigrams_level{level}_n{n_value}.pkl"


def _is_cache_fresh(cache_path: Path, source_path: Path) -> bool:
    """``cache_path`` が存在し ``source_path`` 以降の mtime ならば ``True``。"""
    if not cache_path.exists():
        return False
    if not source_path.exists():
        return True
    return cache_path.stat().st_mtime >= source_path.stat().st_mtime


def _load_features_cache(
    cache_path: Path,
) -> tuple[
    dict[str, dict[int, frozenset]],
    dict[str, dict[int, tuple[tuple[str, str], ...]]],
    dict[str, int],
]:
    """Pickle を読み、 version/schema が一致すれば ``(bigrams, singletons, excluded)`` を返す。

    Raises:
        ValueError: payload の型 / version / schema が想定外のとき。
    """
    with cache_path.open("rb") as f:
        payload = pickle.load(f)  # noqa: S301 -- 自己生成のローカル cache
    if not isinstance(payload, dict):
        raise ValueError(f"unexpected payload type: {type(payload).__name__}")
    if payload.get("version") != NGRAMS_CACHE_VERSION:
        raise ValueError(f"version mismatch: {payload.get('version')!r} != {NGRAMS_CACHE_VERSION}")
    if payload.get("schema") != NGRAMS_CACHE_SCHEMA:
        raise ValueError(f"schema mismatch: {payload.get('schema')!r}")
    bigrams = payload.get("bigrams")
    singletons = payload.get("singletons")
    excluded = payload.get("excluded", {d: 0 for d in DEPTHS})
    if not isinstance(bigrams, dict) or not isinstance(singletons, dict):
        raise ValueError("missing 'bigrams' or 'singletons' in cache payload")
    return bigrams, singletons, excluded


def _write_features_cache(
    input_dir: Path,
    level: int,
    n_value: int,
    bigrams: dict[str, dict[int, frozenset]],
    singletons: dict[str, dict[int, tuple[tuple[str, str], ...]]],
    excluded: dict[str, int],
) -> Path:
    """Features を pickle で書き出す（tmp → rename のアトミック書き）。"""
    cache_path = _features_cache_path(input_dir, level, n_value)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    payload = {
        "version": NGRAMS_CACHE_VERSION,
        "schema": NGRAMS_CACHE_SCHEMA,
        "level": level,
        "n": n_value,
        "bigrams": bigrams,
        "singletons": singletons,
        "excluded": excluded,
    }
    with tmp_path.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_path.replace(cache_path)
    print(f"[CACHE] wrote {cache_path}", flush=True)
    return cache_path


# ---------------------------------------------------------------------------
# Bigram pattern 構築（depth ごと）
# ---------------------------------------------------------------------------


def _build_bigram_patterns(
    bigrams: dict[str, dict[int, frozenset]],
    depth: str,
) -> tuple[list[str], dict[str, frozenset]]:
    """``{mb_id: frozenset}`` から ``(ids, sets)`` を切り出す（depth ごと）。

    Returns:
        ``ids``: cutout_id (``"{mb_id}_{depth}"``) のリスト。
        ``sets``: ``cutout_id → bigram frozenset`` （必ず非空）。
    """
    depth_table = bigrams.get(depth, {})
    ids: list[str] = []
    sets: dict[str, frozenset] = {}
    for mb_id, bg in depth_table.items():
        cutout_id = f"{mb_id}_{depth}"
        ids.append(cutout_id)
        sets[cutout_id] = bg
    return ids, sets


# ---------------------------------------------------------------------------
# Singleton grouping (exact-match)
# ---------------------------------------------------------------------------


def _group_singletons(
    level: int,
    depth: str,
    singletons_depth: dict[int, tuple[tuple[str, str], ...]],
) -> dict[str, list[str]]:
    """Token tuple 完全一致で grouping し、 ``{class_id: [cutout_id, ...]}`` を返す。

    Args:
        level: 抽象化レベル。
        depth: 対象 depth（cutout_id 構築に使用）。
        singletons_depth: ``{mb_id: tuple(tokens)}``。 token tuple の長さは
            ``1`` 以上 ``n_value`` 未満（既定 ``n=2`` ではすべて長さ 1）。

    Returns:
        ``{class_id: sorted member cutout_ids}``（決定的順序）。
    """
    buckets: dict[tuple, list[str]] = {}
    for mb_id, key in singletons_depth.items():
        cutout_id = f"{mb_id}_{depth}"
        buckets.setdefault(key, []).append(cutout_id)
    classes: dict[str, list[str]] = {}
    for key in sorted(buckets):
        members = sorted(buckets[key])
        key_repr = "|".join(f"{name}:{value}" for name, value in key)
        content = f"singleton:{key_repr}:{','.join(members)}"
        class_id = _make_class_id(level, content, prefix="S1")
        classes[class_id] = members
    return classes


# ---------------------------------------------------------------------------
# 並列 Jaccard ペア計算（全ペア、通常モード用）
# ---------------------------------------------------------------------------

# ワーカープロセスが参照するグローバル（initializer / 逐次時は本体で設定）。
_W_IDS: list[str] = []
_W_SETS: dict[str, frozenset] = {}


def _worker_init(ids: list[str], sets: dict[str, frozenset]) -> None:
    """ProcessPoolExecutor initializer: ペア計算用データをワーカーに展開する。"""
    global _W_IDS, _W_SETS
    _W_IDS = ids
    _W_SETS = sets


def _compute_jaccard_chunk(
    i_start: int,
    i_end: int,
    tau: float,
) -> list[tuple[float, str, str]]:
    """ペア ``(i, j)``（``i ∈ [i_start, i_end)``, ``j > i``）の Jaccard を計算する。

    bigram テーブル由来の集合は必ず非空のため、空集合同士で Jaccard=1.0 とする
    特殊扱いは不要（``_extract_features`` 側で除外済み）。
    """
    candidates: list[tuple[float, str, str]] = []
    n = len(_W_IDS)
    for i in range(i_start, min(i_end, n)):
        a_id = _W_IDS[i]
        a_set = _W_SETS[a_id]
        for j in range(i + 1, n):
            b_id = _W_IDS[j]
            b_set = _W_SETS[b_id]
            inter = len(a_set & b_set)
            if inter == 0:
                continue
            union = len(a_set) + len(b_set) - inter
            s = inter / union if union else 0.0
            if s >= tau:
                candidates.append((s, a_id, b_id))
    return candidates


def _make_chunks(n: int, target_chunks: int) -> list[tuple[int, int]]:
    """``[0, n)`` を最大 ``target_chunks`` 個の ``(start, end)`` 区間に分割する。"""
    if target_chunks <= 1 or n <= target_chunks:
        return [(0, n)]
    step = (n + target_chunks - 1) // target_chunks
    return [(i, min(i + step, n)) for i in range(0, n, step)]


def _jaccard_candidates(
    ids: list[str],
    sets: dict[str, frozenset],
    tau: float,
    workers: int,
) -> list[tuple[float, str, str]]:
    """全ペアの Jaccard を計算し、 ``tau`` 以上の候補を逐次順で返す。"""
    n = len(ids)
    if n < 2:
        return []
    if workers <= 1 or n < workers * 2:
        _worker_init(ids, sets)
        return _compute_jaccard_chunk(0, n, tau)

    chunks = _make_chunks(n, max(workers * 4, 1))
    chunk_results: list[tuple[int, list[tuple[float, str, str]]]] = []
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_worker_init,
        initargs=(ids, sets),
    ) as ex:
        futures = {ex.submit(_compute_jaccard_chunk, i0, i1, tau): i0 for i0, i1 in chunks}
        for fut in as_completed(futures):
            chunk_results.append((futures[fut], fut.result()))
    chunk_results.sort(key=lambda x: x[0])
    candidates: list[tuple[float, str, str]] = []
    for _, cand in chunk_results:
        candidates.extend(cand)
    return candidates


# ---------------------------------------------------------------------------
# Bigram 貪欲併合
# ---------------------------------------------------------------------------


def _merge_bigrams(
    level: int,
    ids: list[str],
    candidates: list[tuple[float, str, str]],
    n_value: int,
    tau: float,
) -> dict[str, list[str]]:
    """Jaccard 候補から bigram クラスタを生成する（``tau`` で再フィルタ）。

    旧実装の ``empty_ids`` 一括併合特例は撤去した。 ids は必ず bigram 非空。
    """
    filtered = [(s, a, b) for s, a, b in candidates if s >= tau]
    filtered.sort(key=lambda x: (-x[0], _pair_hash(x[1], x[2])))

    uf = UnionFind(ids)
    for _, a, b in filtered:
        uf.union(a, b)

    classes: dict[str, list[str]] = {}
    for _root, members in sorted(uf.components().items(), key=lambda kv: sorted(kv[1])):
        members_sorted = sorted(members)
        content = f"jaccard:n{n_value}:{','.join(members_sorted)}"
        class_id = _make_class_id(level, content, prefix="M2")
        classes[class_id] = members_sorted
    return classes


def greedy_merge_bigrams(
    level: int,
    ids: list[str],
    sets: dict[str, frozenset],
    n_value: int,
    tau: float,
    workers: int,
) -> dict[str, list[str]]:
    """通常モード: 全ペア Jaccard を計算してから ``tau`` で併合する。"""
    candidates = _jaccard_candidates(ids, sets, tau, workers)
    return _merge_bigrams(level, ids, candidates, n_value, tau)


# ---------------------------------------------------------------------------
# Server モード: 転置インデックス + 候補ペア並列 + 複数 tau 一括
# ---------------------------------------------------------------------------

# 候補ペア類似度計算ワーカーが参照するグローバル（index → n-gram 集合）。
_SIM_SETS: list[frozenset] = []


def _sim_worker_init(sets_list: list[frozenset]) -> None:
    """ProcessPoolExecutor initializer: index→n-gram 集合をワーカーに展開する。"""
    global _SIM_SETS
    _SIM_SETS = sets_list


def _score_pair_chunk(
    pairs: list[tuple[int, int]],
    min_tau: float,
) -> list[tuple[float, int, int]]:
    """候補ペア ``(i, j)`` の Jaccard を計算し ``min_tau`` 以上を返す（index 表現）。"""
    out: list[tuple[float, int, int]] = []
    for i, j in pairs:
        a = _SIM_SETS[i]
        b = _SIM_SETS[j]
        inter = len(a & b)
        if inter == 0:
            continue
        union = len(a) + len(b) - inter
        s = inter / union if union else 0.0
        if s >= min_tau:
            out.append((s, i, j))
    return out


def _candidate_pairs(ids: list[str], sets: dict[str, frozenset]) -> list[tuple[int, int]]:
    """転置インデックスで「共通 n-gram を持つペア」``(i<j)`` を列挙する。"""
    posting: dict = {}
    for idx, cid in enumerate(ids):
        for ng in sets[cid]:
            posting.setdefault(ng, []).append(idx)
    pairs: set[tuple[int, int]] = set()
    for idxs in posting.values():
        m = len(idxs)
        if m < 2:
            continue
        # idxs は enumerate 順 = 昇順なので a<b で常に idxs[a] < idxs[b]。
        for a in range(m):
            ia = idxs[a]
            for b in range(a + 1, m):
                pairs.add((ia, idxs[b]))
    return list(pairs)


def _scored_pairs(
    ids: list[str],
    sets: dict[str, frozenset],
    min_tau: float,
    workers: int,
) -> list[tuple[float, str, str]]:
    """候補ペアの類似度を 1 回だけ計算し ``(s, id_a, id_b)`` を返す。

    複数 tau で再利用できるよう ``min_tau`` 以上の候補のみ計算・保持する。
    """
    sets_list = [sets[c] for c in ids]
    pairs = _candidate_pairs(ids, sets)
    if not pairs:
        return []

    if workers <= 1 or len(pairs) < workers * 2:
        _sim_worker_init(sets_list)
        scored_idx = _score_pair_chunk(pairs, min_tau)
    else:
        chunks = _make_chunks(len(pairs), max(workers * 4, 1))
        scored_idx = []
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_sim_worker_init,
            initargs=(sets_list,),
        ) as ex:
            futures = [ex.submit(_score_pair_chunk, pairs[i0:i1], min_tau) for i0, i1 in chunks]
            for fut in as_completed(futures):
                scored_idx.extend(fut.result())
    return [(s, ids[i], ids[j]) for s, i, j in scored_idx]


# ---------------------------------------------------------------------------
# 出力
# ---------------------------------------------------------------------------


def _tau_dirname(tau: float) -> str:
    """Tau → ``jaccard{NN}`` ディレクトリ名（run.sh 互換: 0.7→jaccard07, 0.9→jaccard09）。"""
    return f"jaccard{round(tau * 10):02d}"


def _write_result(
    out_path: Path,
    level: int,
    depth: str,
    n_value: int,
    tau: float,
    num_bigram_patterns: int,
    num_singleton_patterns: int,
    num_excluded_empty: int,
    bigram_classes: dict[str, list[str]],
    singleton_classes: dict[str, list[str]],
) -> None:
    """1 (tau, level, depth) の bigram + singleton クラスタを統合 JSON で書き出す。

    bigram と singleton のクラスタは class_id の prefix（``M2`` / ``S1``）で
    判別可能なため、 1 つの ``classes`` 辞書に統合して出力する。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    classes: dict[str, list[str]] = {}
    classes.update(bigram_classes)
    classes.update(singleton_classes)
    payload = {
        "meta": {
            "level": level,
            "depth": depth,
            "n": n_value,
            "tau": tau,
            "mode": "jaccard+singleton",
            "num_bigram_patterns": num_bigram_patterns,
            "num_singleton_patterns": num_singleton_patterns,
            "num_excluded_empty": num_excluded_empty,
            "num_bigram_classes": len(bigram_classes),
            "num_singleton_classes": len(singleton_classes),
            "num_classes": len(classes),
        },
        "classes": classes,
    }
    hayalab.write_json(out_path, payload)
    print(
        f"[OUTPUT] {out_path}  (bigram: {num_bigram_patterns}→{len(bigram_classes)}, singleton: {num_singleton_patterns}→{len(singleton_classes)}, excluded: {num_excluded_empty})",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Level 処理
# ---------------------------------------------------------------------------


def process_level(
    level: int,
    bigrams_table: dict[str, dict[int, frozenset]],
    singletons_table: dict[str, dict[int, tuple[tuple[str, str], ...]]],
    excluded_table: dict[str, int],
    output_dir: Path,
    n_value: int,
    tau: float,
    workers: int,
) -> None:
    """通常モード: 1 レベル分を depth ごとに統合し JSON を書き出す。"""
    level_dir = output_dir / f"level{level}"
    level_dir.mkdir(parents=True, exist_ok=True)

    for depth in DEPTHS:
        ids, sets = _build_bigram_patterns(bigrams_table, depth)
        singletons_d = singletons_table.get(depth, {})
        excluded_d = excluded_table.get(depth, 0)

        bigram_classes = greedy_merge_bigrams(level, ids, sets, n_value, tau, workers)
        singleton_classes = _group_singletons(level, depth, singletons_d)

        out_path = level_dir / f"{depth}.json"
        _write_result(
            out_path,
            level,
            depth,
            n_value,
            tau,
            len(ids),
            len(singletons_d),
            excluded_d,
            bigram_classes,
            singleton_classes,
        )


def process_level_server(
    level: int,
    bigrams_table: dict[str, dict[int, frozenset]],
    singletons_table: dict[str, dict[int, tuple[tuple[str, str], ...]]],
    excluded_table: dict[str, int],
    output_dir: Path,
    n_value: int,
    taus: list[float],
    workers: int,
) -> None:
    """Server モード: depth ごと・複数 tau を一括処理する。

    Singleton クラスタは tau 非依存のため depth ごとに 1 回計算し、全 tau で共有する。
    Bigram クラスタは ``min(taus)`` で類似度を 1 回だけ計算し、 tau ごとにフィルタ
    して併合する（候補ペア計算を並列化）。
    """
    min_tau = min(taus)
    for depth in DEPTHS:
        ids, sets = _build_bigram_patterns(bigrams_table, depth)
        singletons_d = singletons_table.get(depth, {})
        excluded_d = excluded_table.get(depth, 0)

        # tau 非依存パート: singleton clusters
        singleton_classes = _group_singletons(level, depth, singletons_d)
        # tau 共通パート: 候補ペアの類似度を 1 回だけ計算
        scored = _scored_pairs(ids, sets, min_tau, workers)

        for tau in taus:
            bigram_classes = _merge_bigrams(level, ids, scored, n_value, tau)
            out_path = output_dir / _tau_dirname(tau) / f"level{level}" / f"{depth}" / f"{depth}.json"
            _write_result(
                out_path,
                level,
                depth,
                n_value,
                tau,
                len(ids),
                len(singletons_d),
                excluded_d,
                bigram_classes,
                singleton_classes,
            )


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。"""
    parser = argparse.ArgumentParser(
        description=("approach_minimum integrate: bigram Jaccard 貪欲併合 + singleton 完全一致 grouping (len=0 cutouts は除外)"),
    )
    parser.add_argument("--input-dir", type=Path, default=None, help="abstract_level{L}.json 置き場")
    parser.add_argument("--output-dir", type=Path, default=None, help="integrate 出力ディレクトリ")
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=[0, 1, 2, 3],
        help="処理する抽象化レベル（入力ファイルが存在するもののみ処理）",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=2,
        help=("n-gram の n (default: 2 = bigram)。 len(tokens) >= n の cutout を bigram 路線、 0 < len(tokens) < n の cutout を singleton 路線に振り分ける。"),
    )
    parser.add_argument("--tau", type=float, default=0.7, help="Jaccard 閾値 (default: 0.7)。通常モードのみ")
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列ワーカー数 (default: os.cpu_count())。1 で逐次実行",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help=("server モード: 転置インデックスで候補ペアを厳密に絞り込み、 類似度を 1 回だけ計算して複数 tau (--taus) を一括出力する。"),
    )
    parser.add_argument(
        "--taus",
        type=float,
        nargs="+",
        default=[0.5, 0.7, 0.9],
        help="server モードで一括処理する Jaccard 閾値群 (default: 0.5 0.7 0.9)",
    )
    parser.add_argument(
        "--create-cache",
        action="store_true",
        help=("features cache pickle (bigrams_level{L}_n{N}.pkl, v2 schema) を生成・更新する。未指定なら cache は読むのみで書かない（in-memory rebuild）。"),
    )
    return parser.parse_args()


def main() -> None:
    """全レベル・全 depth の統合を実行する。"""
    args = parse_args()

    input_dir = args.input_dir or (ROOT / "outputs" / "scam" / "approach_minimum" / "abstract")
    output_dir = args.output_dir or (ROOT / "outputs" / "scam" / "approach_minimum" / "integrate")
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)

    if args.server:
        print(
            f"[CONFIG] MODE=server n={args.n} taus={args.taus} workers={workers} levels={args.levels}",
            flush=True,
        )
    else:
        print(f"[CONFIG] n={args.n} tau={args.tau} workers={workers} levels={args.levels}", flush=True)

    for level in args.levels:
        in_path = input_dir / f"abstract_level{level}.json"
        cache_path = _features_cache_path(input_dir, level, args.n)

        features: tuple[dict, dict, dict] | None = None

        # 1. --create-cache 未指定 かつ cache が新鮮なら pickle を load
        if not args.create_cache and _is_cache_fresh(cache_path, in_path):
            try:
                features = _load_features_cache(cache_path)
                print(f"[CACHE] fresh, loading from pickle: {cache_path}", flush=True)
            except (ValueError, pickle.UnpicklingError, EOFError) as e:
                print(f"[CACHE] load failed ({e}), falling back to JSON", flush=True)
                features = None

        # 2. cache 不在 / 古い / 破損 / --create-cache 指定: abstract から再構築
        if features is None:
            if not in_path.exists():
                print(f"[SKIP] not found: {in_path}", flush=True)
                continue
            print(f"[INPUT] {in_path}", flush=True)
            records = hayalab.read_json(in_path)
            print(f"[RECORDS] level{level}: {len(records)}", flush=True)
            features = _extract_features(records, DEPTHS, args.n)
            # records は features に取り込み済みのため、メモリ解放する（abstract は数 GB 規模）。
            del records
            if args.create_cache:
                _write_features_cache(input_dir, level, args.n, *features)
            else:
                print("[CACHE] no cache write (use --create-cache to persist)", flush=True)

        bigrams_table, singletons_table, excluded_table = features

        # 振り分け件数のログ
        for depth in DEPTHS:
            print(
                f"[FEATURES] level{level} {depth}: bigram={len(bigrams_table.get(depth, {}))}, singleton={len(singletons_table.get(depth, {}))}, excluded(empty)={excluded_table.get(depth, 0)}",
                flush=True,
            )

        if args.server:
            process_level_server(
                level,
                bigrams_table,
                singletons_table,
                excluded_table,
                output_dir,
                args.n,
                args.taus,
                workers,
            )
        else:
            process_level(
                level,
                bigrams_table,
                singletons_table,
                excluded_table,
                output_dir,
                args.n,
                args.tau,
                workers,
            )


if __name__ == "__main__":
    main()
