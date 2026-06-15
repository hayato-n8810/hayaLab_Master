"""approach 統合: 三本立て (bigram Jaccard + unigram 完全一致 + empty 除外).

処理概要:

1. 入力 ``abstract_level{L}.json`` を読み込む。
2. Diff / Brother / ExParent / Parent の各 depth について、 cutout の有効
   トークン列 (``variadic=True`` を除外したノード列) の長さ ``n_t`` で振り分ける。

   * ``n_t == 0`` ： 除外（クラスタ生成対象外）。 cutout は存在するが
     全ノードが variadic で抽象化後に有効トークンが残らないケース。
   * ``0 < n_t < n``： unigram: token tuple 完全一致で grouping。
     既定 ``n=2`` のとき ``n_t == 1`` のみ該当。
   * ``n_t >= n`` ：生成される各 bigram クラスタについてクラスタ内の任意の 2 メンバー (x, y) は Jaccard(x, y) >= tau

3. depth ごとに「bigram クラスタ」+「unigram クラスタ」を 1 つの ``classes``
   辞書に統合して JSON で書き出す。 ``class_id`` の prefix で由来を判別できる
   (``L*_M2_*``: bigram, ``L*_U1_*``: unigram)。

トークン化規約:

* 各ノードを ``(name, normalize_value(value))`` の 2 要素タプルに縮約。
* value は slot タイプのみに正規化 (``$v0`` → ``$v`` 等、prefix v/f/k/n/s)。
  ``$api`` は番号なしのため素通し。
* ``variadic=True`` のノードは集約鍵から除外する（子サブツリーは含む）。

cutout_id は ``"{mb_id}_{depth}"`` 形式。 depth ごとに独立して併合するため、
クラスタのメンバーはこの cutout_id 文字列で表現される。

各出力 JSON のスキーマ::

    {
        "meta": {
            "level": int, "depth": str, "n": int, "tau": float,
            "mode": "jaccard+unigram",
            "num_bigram_patterns": int,
            "num_unigram_patterns": int,
            "num_excluded_empty": int,
            "num_bigram_classes": int,
            "num_unigram_classes": int,
            "num_classes": int,
        },
        "classes": {class_id: [cutout_id, ...], ...}
    }

class_id prefix:

* ``L{level}_M2_{hash8}``: bigram Jaccard 由来のクラスタ。
* ``L{level}_U1_{hash8}``: unigram 完全一致 由来のクラスタ。

Cache pickle (v3):
    outputs/scam/approach/abstract/bigrams_level{L}_n{N}.pkl
    {
        "version": 3,
        "schema": "abst_id_to_features_v3",
        "level": L,
        "n": N,
        "bigrams":  {depth: {mb_id: frozenset(bigrams)}},  # n_t >= n のみ
        "unigrams": {depth: {mb_id: tuple(tokens)}},       # 0 < n_t < n のみ
        "excluded": {depth: int},                          # n_t == 0 の件数
    }

アルゴリズム

1. **完全一致の事前グルーピング**: bigram 集合 (frozenset) が完全一致する cutout
   は Jaccard=1.0 で自明にクリークを成すため、1 つの「代表」にまとめてから類似度
   計算する（同一集合同士の計算を省く）。
2. **転置インデックス候補**: 代表間の類似度は [integrate._scored_pairs](integrate.py)
   を流用し、共通 n-gram を 1 つ以上持つペアのみ計算する。共通 n-gram が 0 のペアは
   Jaccard=0 で必ず tau 未満のため、候補集合に現れないことをもって「併合不可」と
   判定できる（全ペア O(n^2) を回す必要はない）。
3. **complete-linkage 貪欲併合**: 候補ペアを (類似度降順, pair_hash) 順に走査し、
   2 クラスタの cross ペアが全て候補集合 (s>=tau のペア集合) に含まれるときのみ併合
   する。初期状態（各代表が単独クラスタ）で不変条件は自明に成り立ち、併合時に cross
   全ペアを検査することで不変条件が保たれる。

unigram クラスタは [integrate._group_unigrams](integrate.py) の完全一致 grouping をそのまま使う

入力:
    outputs/scam/approach/abstract/abstract_level{1,2}.json
    （cache: bigrams_level{L}_n{N}.pkl）

出力:
    outputs/scam/approach/integrate/jaccard{NN}/level{L}/{depth}/{depth}.json

実行例:
    uv run python experiments/scam/approach/integrate.py --taus 0.7 0.9 --workers 40
    uv run python experiments/scam/approach/integrate.py --levels 0 --taus 0.7
"""

from __future__ import annotations

import argparse
import os
import pickle
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path

import hayalab

# bigram + unigram + excluded の三本立て
# 互換性のない古い cache は自動的に invalid 扱いとなる。
NGRAMS_CACHE_VERSION = 2
NGRAMS_CACHE_SCHEMA = "abst_id_to_features_v2"

# slot 番号正規化: ``$v0`` → ``$v``。prefix v/f/k/n/s に続く数字を捨てる。
# ``$api`` は数字を持たないためマッチせず素通しになる。
_SLOT_NUM_RE = re.compile(r"^\$([vfkns])\d+$")

# cutout depth の順序（出力スキーマ安定化のため固定）。
DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")
# リポジトリルート（experiments/scam/approach/integrate.py の 3 つ上）。
ROOT = Path(__file__).resolve().parents[3]


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
# Unigram grouping (exact-match)
# ---------------------------------------------------------------------------


def _group_unigrams(
    level: int,
    depth: str,
    unigrams_depth: dict[int, tuple[tuple[str, str], ...]],
) -> dict[str, list[str]]:
    """Token tuple 完全一致で grouping し、 ``{class_id: [cutout_id, ...]}`` を返す。

    Args:
        level: 抽象化レベル。
        depth: 対象 depth（cutout_id 構築に使用）。
        unigrams_depth: ``{mb_id: tuple(tokens)}``。 token tuple の長さは
            ``1`` 以上 ``n_value`` 未満（既定 ``n=2`` ではすべて長さ 1）。

    Returns:
        ``{class_id: sorted member cutout_ids}``（決定的順序）。
    """
    buckets: dict[tuple, list[str]] = {}
    for mb_id, key in unigrams_depth.items():
        cutout_id = f"{mb_id}_{depth}"
        buckets.setdefault(key, []).append(cutout_id)
    classes: dict[str, list[str]] = {}
    for key in sorted(buckets):
        members = sorted(buckets[key])
        key_repr = "|".join(f"{name}:{value}" for name, value in key)
        content = f"unigram:{key_repr}:{','.join(members)}"
        class_id = _make_class_id(level, content, prefix="U1")
        classes[class_id] = members
    return classes


# ---------------------------------------------------------------------------
# 完全一致の事前グルーピング
# ---------------------------------------------------------------------------


def _pair_hash(a: str, b: str) -> str:
    """ペア ``(a, b)`` の順序非依存ハッシュ（候補ソートのタイブレーク用）。"""
    return sha256("::".join(sorted((a, b))).encode("utf-8")).hexdigest()


def _make_class_id(level: int, content: str, prefix: str) -> str:
    """``L{level}_{prefix}_{hash8}`` 形式の class ID を生成する。

    Args:
        level: 抽象化レベル。
        content: ハッシュ元の文字列（生成戦略 + メンバー情報を含む）。
        prefix: 由来を示す短い識別子 (``M2``: bigram, ``U1``: unigram)。
    """
    return f"L{level}_{prefix}_{sha256(content.encode('utf-8')).hexdigest()[:8]}"


def _group_identical(
    ids: list[str],
    sets: dict[str, frozenset],
) -> tuple[list[str], dict[str, frozenset], dict[str, list[str]]]:
    """bigram 集合が完全一致する cutout を 1 代表にまとめる。

    完全一致集合同士は Jaccard=1.0 で自明にクリークを成すため、代表だけで類似度
    計算・併合判定を行えば計算量を削減できる（同一集合同士の計算を省く）。

    Args:
        ids: cutout_id のリスト。
        sets: ``cutout_id -> bigram frozenset``。

    Returns:
        ``(rep_ids, rep_sets, rep_members)``。

        * ``rep_ids``: 代表 cutout_id のリスト（決定的順序）。各グループの
          メンバーのうち辞書順最小を代表に採る。
        * ``rep_sets``: ``代表 -> bigram frozenset``。
        * ``rep_members``: ``代表 -> グループ全メンバー（代表自身を含む、ソート済み）``。
    """
    groups: dict[frozenset, list[str]] = {}
    for cid in ids:
        groups.setdefault(sets[cid], []).append(cid)

    rep_ids: list[str] = []
    rep_sets: dict[str, frozenset] = {}
    rep_members: dict[str, list[str]] = {}
    for key, members in groups.items():
        members_sorted = sorted(members)
        rep = members_sorted[0]
        rep_ids.append(rep)
        rep_sets[rep] = key
        rep_members[rep] = members_sorted
    rep_ids.sort()
    return rep_ids, rep_sets, rep_members


# ---------------------------------------------------------------------------
# complete-linkage 貪欲併合
# ---------------------------------------------------------------------------


def _ekey(a: str, b: str) -> tuple[str, str]:
    """順序非依存のクラスタペアキー（辞書順で正規化）。"""
    return (a, b) if a < b else (b, a)


def _complete_merge_bigrams(
    level: int,
    rep_ids: list[str],
    rep_members: dict[str, list[str]],
    scored: list[tuple[float, str, str]],
    n_value: int,
    tau: float,
) -> dict[str, list[str]]:
    """代表間の候補から complete-linkage で bigram クラスタを生成する。

    候補ペアを (類似度降順, pair_hash) 順に走査し、2 クラスタが「完全二部結合」
    （全頂点ペアが候補辺で結ばれている）であるときのみ併合する。これにより
    「クラスタ内の任意の 2 代表が tau 以上」という不変条件が保たれる。最後に各代表を
    その完全一致メンバーへ展開してクラスタを構成する（展開後も不変条件は維持される）。

    効率化（cross 判定の O(1) 化）:
        単純実装は併合のたびに ``|Ca|*|Cb|`` 個の cross ペアを候補集合と照合するため
        クラスタが育つと二次的に重い。本実装は **クラスタペア間の候補辺数** を
        ``cross[(root_a, root_b)]`` に保持し、併合可能条件を
        ``cross[(Ca, Cb)] == size[Ca] * size[Cb]`` の O(1) 比較で判定する
        （完全二部結合 ⟺ cross 辺数が頂点ペア数に一致）。併合時は吸収される側の
        隣接クラスタへの辺数を残す側へ加算するだけ（``O(deg)``）で、走査全体は
        候補辺が疎な限り高速。

    Args:
        level: 抽象化レベル。
        rep_ids: 代表 cutout_id のリスト（クラスタ初期化に使用）。
        rep_members: ``代表 -> 完全一致メンバー列``（展開に使用）。
        scored: ``(s, id_a, id_b)`` の候補（``s >= min(taus)`` 済み、代表間のみ）。
        n_value: n-gram の n（class_id content 用）。
        tau: Jaccard 閾値。

    Returns:
        ``{class_id: sorted member cutout_ids}``（決定的順序）。
    """
    # tau でフィルタし、高類似度優先で走査する（同点は pair_hash で決定的に
    # タイブレーク。 integrate.py と同方針）。
    filtered = [(s, a, b) for s, a, b in scored if s >= tau]
    filtered.sort(key=lambda x: (-x[0], _pair_hash(x[1], x[2])))

    # クラスタ管理: Union-Find（経路圧縮）+ サイズ + 代表メンバー列。
    parent: dict[str, str] = {r: r for r in rep_ids}
    size: dict[str, int] = {r: 1 for r in rep_ids}
    members_of: dict[str, list[str]] = {r: [r] for r in rep_ids}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    # cross[(root_a, root_b)] = 2 クラスタ間の候補辺数。adj[root] = 隣接 root 集合。
    # 初期は各代表が単独クラスタなので、候補辺 (a, b) はそのまま頂点ペアの辺 1 本。
    cross: dict[tuple[str, str], int] = {}
    adj: dict[str, set[str]] = {r: set() for r in rep_ids}
    for _s, a, b in filtered:
        k = _ekey(a, b)
        if k not in cross:
            cross[k] = 0
            adj[a].add(b)
            adj[b].add(a)
        cross[k] += 1

    for _s, a, b in filtered:
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        # 完全二部結合のときのみ併合可能。
        if cross.get(_ekey(ra, rb), 0) != size[ra] * size[rb]:
            continue
        # 大きいクラスタを残して吸収（同サイズは辞書順で決定的に）。
        if size[ra] < size[rb] or (size[ra] == size[rb] and rb < ra):
            ra, rb = rb, ra
        # 吸収される rb の隣接辺を ra 側へ付け替え・加算する。
        for x in list(adj[rb]):
            if x == ra:
                continue
            cnt = cross.pop(_ekey(rb, x))
            kx = _ekey(ra, x)
            cross[kx] = cross.get(kx, 0) + cnt
            adj[x].discard(rb)
            adj[x].add(ra)
            adj[ra].add(x)
        # ra-rb 間の辺・隣接を掃除して union する。
        adj[ra].discard(rb)
        cross.pop(_ekey(ra, rb), None)
        del adj[rb]
        parent[rb] = ra
        size[ra] += size[rb]
        members_of[ra].extend(members_of[rb])
        del members_of[rb]

    # 代表クラスタを完全一致メンバーへ展開し、決定的順序で class 化する。
    expanded: list[list[str]] = []
    for reps in members_of.values():
        cutouts: list[str] = []
        for rep in reps:
            cutouts.extend(rep_members[rep])
        expanded.append(sorted(cutouts))
    expanded.sort()

    classes: dict[str, list[str]] = {}
    for members_sorted in expanded:
        content = f"jaccard_complete:n{n_value}:{','.join(members_sorted)}"
        class_id = _make_class_id(level, content, prefix="M2")
        classes[class_id] = members_sorted
    return classes


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


def _make_chunks(n: int, target_chunks: int) -> list[tuple[int, int]]:
    """``[0, n)`` を最大 ``target_chunks`` 個の ``(start, end)`` 区間に分割する。"""
    if target_chunks <= 1 or n <= target_chunks:
        return [(0, n)]
    step = (n + target_chunks - 1) // target_chunks
    return [(i, min(i + step, n)) for i in range(0, n, step)]


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
    num_unigram_patterns: int,
    num_excluded_empty: int,
    bigram_classes: dict[str, list[str]],
    unigram_classes: dict[str, list[str]],
) -> None:
    """1 (tau, level, depth) の bigram + unigram クラスタを統合 JSON で書き出す。

    bigram と unigram のクラスタは class_id の prefix（``M2`` / ``U1``）で
    判別可能なため、 1 つの ``classes`` 辞書に統合して出力する。
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    classes: dict[str, list[str]] = {}
    classes.update(bigram_classes)
    classes.update(unigram_classes)
    payload = {
        "meta": {
            "level": level,
            "depth": depth,
            "n": n_value,
            "tau": tau,
            "mode": "jaccard+unigram",
            "num_bigram_patterns": num_bigram_patterns,
            "num_unigram_patterns": num_unigram_patterns,
            "num_excluded_empty": num_excluded_empty,
            "num_bigram_classes": len(bigram_classes),
            "num_unigram_classes": len(unigram_classes),
            "num_classes": len(classes),
        },
        "classes": classes,
    }
    hayalab.write_json(out_path, payload)
    print(
        f"[OUTPUT] {out_path}  (bigram: {num_bigram_patterns}→{len(bigram_classes)}, unigram: {num_unigram_patterns}→{len(unigram_classes)}, excluded: {num_excluded_empty})",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Level 処理（complete-linkage, 複数 tau 一括）
# ---------------------------------------------------------------------------


def process_level_complete(
    level: int,
    bigrams_table: dict[str, dict[int, frozenset]],
    unigrams_table: dict[str, dict[int, tuple[tuple[str, str], ...]]],
    excluded_table: dict[str, int],
    output_dir: Path,
    n_value: int,
    taus: list[float],
    workers: int,
) -> None:
    """1 レベル分を depth ごと・複数 tau で complete-linkage 統合し JSON を書き出す。

    完全一致グルーピングと候補類似度計算は tau 非依存のため depth ごとに 1 回行い、
    complete-linkage 併合のみ tau ごとに繰り返す（候補集合の構築・cross 判定は
    各 tau で再実行する）。 unigram クラスタは tau 非依存で全 tau 共有する。
    """
    min_tau = min(taus)
    for depth in DEPTHS:
        ids, sets = _build_bigram_patterns(bigrams_table, depth)
        unigrams_d = unigrams_table.get(depth, {})
        excluded_d = excluded_table.get(depth, 0)

        # tau 非依存パート
        unigram_classes = _group_unigrams(level, depth, unigrams_d)
        rep_ids, rep_sets, rep_members = _group_identical(ids, sets)
        scored = _scored_pairs(rep_ids, rep_sets, min_tau, workers)
        print(
            f"[GROUP] level{level} {depth}: patterns={len(ids)} reps={len(rep_ids)} scored_pairs={len(scored)}",
            flush=True,
        )

        for tau in taus:
            bigram_classes = _complete_merge_bigrams(level, rep_ids, rep_members, scored, n_value, tau)
            out_path = output_dir / _tau_dirname(tau) / f"level{level}" / f"{depth}" / f"{depth}.json"
            _write_result(
                out_path,
                level,
                depth,
                n_value,
                tau,
                len(ids),
                len(unigrams_d),
                excluded_d,
                bigram_classes,
                unigram_classes,
            )


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
    """Pickle を読み、 version/schema が一致すれば ``(bigrams, unigrams, excluded)`` を返す。

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
    unigrams = payload.get("unigrams")
    excluded = payload.get("excluded", {d: 0 for d in DEPTHS})
    if not isinstance(bigrams, dict) or not isinstance(unigrams, dict):
        raise ValueError("missing 'bigrams' or 'unigrams' in cache payload")
    return bigrams, unigrams, excluded


def _write_features_cache(
    input_dir: Path,
    level: int,
    n_value: int,
    bigrams: dict[str, dict[int, frozenset]],
    unigrams: dict[str, dict[int, tuple[tuple[str, str], ...]]],
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
        "unigrams": unigrams,
        "excluded": excluded,
    }
    with tmp_path.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_path.replace(cache_path)
    print(f"[CACHE] wrote {cache_path}", flush=True)
    return cache_path


# ---------------------------------------------------------------------------
# Feature extraction (三本立て: bigram / unigram / excluded)
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
    * ``0 < n_t < n_value``  → ``unigrams[depth][mb_id]`` に token tuple を格納。

    Args:
        records: ``abstract_level{L}.json`` の読み込み結果。
        depths: 対象 depth 群。
        n_value: n-gram の n（既定 2）。

    Returns:
        ``(bigrams, unigrams, excluded)``。 ``cutout`` 自体が存在しない
        ``(mb_id, depth)`` ペアはどのテーブルにも現れない（既存挙動と整合）。
    """
    bigrams: dict[str, dict[int, frozenset]] = {d: {} for d in depths}
    unigrams: dict[str, dict[int, tuple[tuple[str, str], ...]]] = {d: {} for d in depths}
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
                unigrams[depth][mb_id] = tuple(tokens)
    return bigrams, unigrams, excluded


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。"""
    parser = argparse.ArgumentParser(
        description=("approach integrate (complete-linkage): クラスタ内全ペアが tau 以上を保証する bigram 併合 + unigram 完全一致 grouping (len=0 cutouts は除外)"),
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
        help="n-gram の n (default: 2 = bigram)。integrate.py と同じ振り分け規約。",
    )
    parser.add_argument(
        "--taus",
        type=float,
        nargs="+",
        default=[0.7, 0.9],
        help="一括処理する Jaccard 閾値群 (default: 0.7 0.9)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列ワーカー数 (default: os.cpu_count())。1 で逐次実行",
    )
    parser.add_argument(
        "--create-cache",
        action="store_true",
        help="features cache pickle (integrate.py と共有) を生成・更新する。未指定なら読むのみ。",
    )
    return parser.parse_args()


def main() -> None:
    """全レベル・全 depth の complete-linkage 統合を実行する。"""
    args = parse_args()

    input_dir = args.input_dir or (ROOT / "outputs" / "scam" / "approach" / "abstract")
    output_dir = args.output_dir or (ROOT / "outputs" / "scam" / "approach" / "integrate")
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)

    print(
        f"[CONFIG] MODE=complete-linkage n={args.n} taus={args.taus} workers={workers} levels={args.levels}",
        flush=True,
    )

    for level in args.levels:
        in_path = input_dir / f"abstract_level{level}.json"
        cache_path = _features_cache_path(input_dir, level, args.n)

        features: tuple[dict, dict, dict] | None = None

        # 1. --create-cache 未指定 かつ cache が新鮮なら pickle を load（integrate と共有）
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
            del records
            if args.create_cache:
                _write_features_cache(input_dir, level, args.n, *features)
            else:
                print("[CACHE] no cache write (use --create-cache to persist)", flush=True)

        bigrams_table, unigrams_table, excluded_table = features

        for depth in DEPTHS:
            print(
                f"[FEATURES] level{level} {depth}: bigram={len(bigrams_table.get(depth, {}))}, unigram={len(unigrams_table.get(depth, {}))}, excluded(empty)={excluded_table.get(depth, 0)}",
                flush=True,
            )

        process_level_complete(
            level,
            bigrams_table,
            unigrams_table,
            excluded_table,
            output_dir,
            args.n,
            args.taus,
            workers,
        )


if __name__ == "__main__":
    main()
