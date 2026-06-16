"""bigram complete-linkage 併合とそのヘルパー群（純関数 / pickle 不要）。

ProcessPoolExecutor の起動・並列スコアリング・cache I/O は experiments 側に置く。
本モジュールは「集合・リスト → 集合・リスト」の独立した処理ユニットのみを提供する。

class_id prefix:

* ``L{level}_M2_{hash8}``: bigram Jaccard 由来のクラスタ。
* ``L{level}_U1_{hash8}``: unigram 完全一致 由来のクラスタ。
"""

from __future__ import annotations

from hashlib import sha256

from .tokens import ngrams, tokens_from_nodes


def pair_hash(a: str, b: str) -> str:
    """ペア ``(a, b)`` の順序非依存ハッシュ（候補ソートのタイブレーク用）。"""
    return sha256("::".join(sorted((a, b))).encode("utf-8")).hexdigest()


def make_class_id(level: int, content: str, prefix: str) -> str:
    """``L{level}_{prefix}_{hash8}`` 形式の class ID を生成する。

    Args:
        level: 抽象化レベル。
        content: ハッシュ元の文字列（生成戦略 + メンバー情報を含む）。
        prefix: 由来を示す短い識別子 (``M2``: bigram, ``U1``: unigram)。
    """
    return f"L{level}_{prefix}_{sha256(content.encode('utf-8')).hexdigest()[:8]}"


def ekey(a: str, b: str) -> tuple[str, str]:
    """順序非依存のクラスタペアキー（辞書順で正規化）。"""
    return (a, b) if a < b else (b, a)


def extract_features(
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
            tokens = tokens_from_nodes(cutout.get("nodes", []))
            n_t = len(tokens)
            if n_t == 0:
                excluded[depth] += 1
            elif n_t >= n_value:
                bigrams[depth][mb_id] = frozenset(ngrams(tokens, n_value))
            else:
                unigrams[depth][mb_id] = tuple(tokens)
    return bigrams, unigrams, excluded


def build_bigram_patterns(
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


def group_unigrams(
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
        class_id = make_class_id(level, content, prefix="U1")
        classes[class_id] = members
    return classes


def group_identical(
    ids: list[str],
    sets: dict[str, frozenset],
) -> tuple[list[str], dict[str, frozenset], dict[str, list[str]]]:
    """Bigram 集合が完全一致する cutout を 1 代表にまとめる。

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


def candidate_pairs(ids: list[str], sets: dict[str, frozenset]) -> list[tuple[int, int]]:
    """転置インデックスで「共通 n-gram を持つペア」``(i<j)`` を列挙する。

    Jaccard=0 のペア（共通 n-gram なし）は閾値未満で必ず併合されないため、
    候補集合に現れないことで「併合不可」を判定できる。
    """
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


def make_chunks(n: int, target_chunks: int) -> list[tuple[int, int]]:
    """``[0, n)`` を最大 ``target_chunks`` 個の ``(start, end)`` 区間に分割する。"""
    if target_chunks <= 1 or n <= target_chunks:
        return [(0, n)]
    step = (n + target_chunks - 1) // target_chunks
    return [(i, min(i + step, n)) for i in range(0, n, step)]


def complete_merge_bigrams(
    level: int,
    rep_ids: list[str],
    rep_members: dict[str, list[str]],
    scored: list[tuple[float, str, str]],
    n_value: int,
    tau: float,
) -> dict[str, list[str]]:
    """代表間の候補から complete-linkage で bigram クラスタを生成する。

    候補ペアを (類似度降順, pair_hash) 順に走査し、 2 クラスタが「完全二部結合」
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
    # タイブレーク）。
    filtered = [(s, a, b) for s, a, b in scored if s >= tau]
    filtered.sort(key=lambda x: (-x[0], pair_hash(x[1], x[2])))

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
        k = ekey(a, b)
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
        if cross.get(ekey(ra, rb), 0) != size[ra] * size[rb]:
            continue
        # 大きいクラスタを残して吸収（同サイズは辞書順で決定的に）。
        if size[ra] < size[rb] or (size[ra] == size[rb] and rb < ra):
            ra, rb = rb, ra
        # 吸収される rb の隣接辺を ra 側へ付け替え・加算する。
        for x in list(adj[rb]):
            if x == ra:
                continue
            cnt = cross.pop(ekey(rb, x))
            kx = ekey(ra, x)
            cross[kx] = cross.get(kx, 0) + cnt
            adj[x].discard(rb)
            adj[x].add(ra)
            adj[ra].add(x)
        # ra-rb 間の辺・隣接を掃除して union する。
        adj[ra].discard(rb)
        cross.pop(ekey(ra, rb), None)
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
        class_id = make_class_id(level, content, prefix="M2")
        classes[class_id] = members_sorted
    return classes
