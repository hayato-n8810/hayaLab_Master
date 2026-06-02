"""approach_minimum 統合: n-gram + Jaccard 係数による貪欲併合 (self-contained).

処理概要:

1. 入力 ``abstract_level{L}.json`` を読み込む。
2. Diff / Brother / ExParent / Parent の各 depth について、各 MB の cutout を
   1 つの Pattern とみなし n-gram 集合を作る。
3. 全ペアの Jaccard 係数を計算し、閾値 ``tau`` 以上のペアを類似度降順で
   Union-Find に貪欲併合する（推移的に連結成分 = クラスタを形成）。
4. depth ごとにクラスタ結果を JSON で書き出す。

トークン化規約 (m2_path_ngram.py と共通):

* 各ノードを ``(name, normalize_value(value))`` の 2 要素タプルに縮約。
* value は slot タイプのみに正規化 (``$v0`` → ``$v`` 等、prefix v/f/k/n/s)。
  ``$api`` は番号なしのため素通し。
* ``variadic=True`` のノードは集約鍵から除外する（子サブツリーは含む）。

cutout_id は ``"{mb_id}_{depth}"`` 形式。depth ごとに独立して併合するため、
クラスタのメンバーはこの cutout_id 文字列で表現される。

入力:
    outputs/scam/approach_minimum/abstract/abstract_level{0,1,2,3}.json

出力:
    outputs/scam/approach_minimum/integrate/level{0,1,2,3}/{Diff,Brother,ExParent,Parent}.json

各出力 JSON のスキーマ::

    {
        "meta": {"level": int, "depth": str, "n": int, "tau": float,
                 "mode": "jaccard", "num_patterns": int, "num_classes": int},
        "classes": {class_id: [cutout_id, ...], ...}
    }

計算量: depth あたり O(N^2 * n)（N = その depth の Pattern 数）。N が大きい
場合は ``--workers`` による並列化を推奨する。

実行例:
    uv run python experiments/scam/approach_minimum/integrate.py --workers 7
    uv run python experiments/scam/approach_minimum/integrate.py --levels 0 --n 3 --tau 0.7
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path

logger = logging.getLogger(__name__)

# cutout depth の順序（出力スキーマ安定化のため固定）。
DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")

# リポジトリルート（experiments/scam/approach_minimum/integrate.py の 3 つ上）。
ROOT = Path(__file__).resolve().parents[3]

# n-gram キャッシュ pickle のスキーマバージョン。トークン化規約や格納形を
# 変更した場合に bump し、 古い cache を自動的に無効化する。
NGRAMS_CACHE_VERSION = 1

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
    """``variadic=True`` のノードを除外したトークン列を返す。

    Args:
        nodes: cutout の ``nodes`` リスト（abstract 出力スキーマの生 dict）。

    Returns:
        ノード出現順の ``(name, normalized_value)`` タプル列。
    """
    return [_node_token(n) for n in nodes if not n.get("variadic", False)]


def _ngrams(tokens: list[tuple[str, str]], n: int) -> list[tuple]:
    """トークン列から n-gram（n 個連続トークンのタプル）の列を返す。

    Args:
        tokens: ``_tokens`` が返すトークン列。
        n: n-gram の n（n=2 で bigram）。

    Returns:
        位置順の n-gram タプル列。``len(tokens) < n`` のとき空リスト。
    """
    if len(tokens) < n:
        return []
    return [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


# ---------------------------------------------------------------------------
# Union-Find / class_id 生成 (cluster.py 相当)
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


def _make_class_id(level: int, content: str) -> str:
    """``L{level}_M2_{hash8}`` 形式の class ID を生成する。"""
    return f"L{level}_M2_{_content_hash(content)}"


def _pair_hash(a: str, b: str) -> str:
    """ペア ``(a, b)`` の順序非依存ハッシュ（候補ソートのタイブレーク用）。"""
    return sha256("::".join(sorted((a, b))).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 並列 Jaccard ペア計算
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

    逐次のネスト for ループと同じ放出順なので、chunk 結果を ``i_start`` 順に
    連結すれば逐次実行と同一の候補列を再現できる。

    Returns:
        ``tau`` 以上のペア ``(similarity, id_i, id_j)`` のリスト。
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
    """全ペアの Jaccard を計算し、``tau`` 以上の候補を逐次順で返す。

    ``workers <= 1`` または要素数が少ない場合は逐次計算、それ以外は
    ProcessPoolExecutor で i 区間を分割して並列計算する。並列時も chunk を
    ``i_start`` 順に連結するため、出力候補列は逐次と同一になる。
    """
    n = len(ids)
    if n < 2:
        return []

    if workers <= 1 or n < workers * 2:
        _worker_init(ids, sets)
        return _compute_jaccard_chunk(0, n, tau)

    # 大きなデータは initargs でワーカーへ直接渡す（一時ファイルを作らず、
    # ディスク容量に依存しない）。
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
# 貪欲併合
# ---------------------------------------------------------------------------


def greedy_merge(
    level: int,
    ids: list[str],
    sets: dict[str, frozenset],
    n_value: int,
    tau: float,
    workers: int,
) -> dict[str, list[str]]:
    """n-gram 集合の Jaccard 係数で貪欲併合し、クラスタ辞書を返す。

    Args:
        level: 抽象化レベル（class_id 生成に使用）。
        ids: 対象 cutout_id のリスト。
        sets: cutout_id → n-gram の frozenset。
        n_value: n-gram の n（メタ情報・class_id に反映）。
        tau: Jaccard 閾値（このペア以上を併合）。
        workers: 並列ワーカー数。

    Returns:
        ``{class_id: sorted member cutout_ids}``。
    """
    candidates = _jaccard_candidates(ids, sets, tau, workers)

    uf = UnionFind(ids)
    # 類似度降順 + ペアハッシュで決定的な処理順にする（連結成分自体は順序
    # 非依存だが、再現性のため安定化する）。
    candidates.sort(key=lambda x: (-x[0], _pair_hash(x[1], x[2])))
    for _, a, b in candidates:
        uf.union(a, b)

    classes: dict[str, list[str]] = {}
    for _root, members in sorted(uf.components().items(), key=lambda kv: sorted(kv[1])):
        members_sorted = sorted(members)
        class_id = _make_class_id(level, f"jaccard:n{n_value}:{','.join(members_sorted)}")
        classes[class_id] = members_sorted
    return classes


# ---------------------------------------------------------------------------
# Pattern 構築 / レベル処理
# ---------------------------------------------------------------------------


def _build_id_to_ngrams_table(
    records: list[dict],
    depths: tuple[str, ...],
    n_value: int,
) -> dict[str, dict[int, frozenset]]:
    """1 レベル分の records から ``{depth: {mb_id: frozenset(n-grams)}}`` を作る。

    integrate のクラスタリングと Representative_value 戦略の双方で利用する
    "n-gram テーブルの正規源" となる関数。同じ records を depth ごとに何度も
    走査せず、 1 回のレコードスキャンで全 depth 分をまとめる。

    Args:
        records: ``abstract_level{L}.json`` の読み込み結果。
        depths: 対象 depth 群（出力キーになる）。
        n_value: n-gram の n（n=2 で bigram）。

    Returns:
        ``{depth: {mb_id: frozenset(n-grams)}}``。 cutout が無い (mb_id, depth)
        ペアはエントリ自体を持たない（``_build_patterns`` の挙動と整合）。
    """
    table: dict[str, dict[int, frozenset]] = {d: {} for d in depths}
    for entry in records:
        mb_id = entry["id"]
        cutouts = entry.get("cutouts", {})
        for depth in depths:
            cutout = cutouts.get(depth)
            if not cutout:
                continue
            tokens = _tokens(cutout.get("nodes", []))
            table[depth][mb_id] = frozenset(_ngrams(tokens, n_value))
    return table


def _build_patterns_from_table(
    table: dict[str, dict[int, frozenset]],
    depth: str,
) -> tuple[list[str], dict[str, frozenset]]:
    """テーブルから cutout_id 形式の ``(ids, sets)`` を切り出す。

    既存 ``_build_patterns`` と同一の戻り値（ids の順序、 sets の中身）を保つ。
    呼び出し側のクラスタリング処理は変更不要。
    """
    depth_table = table.get(depth, {})
    ids: list[str] = []
    sets: dict[str, frozenset] = {}
    for mb_id, bg in depth_table.items():
        cutout_id = f"{mb_id}_{depth}"
        ids.append(cutout_id)
        sets[cutout_id] = bg
    return ids, sets


def _ngrams_cache_path(input_dir: Path, level: int, n_value: int) -> Path:
    """``abstract/bigrams_level{L}_n{N}.pkl`` のパスを返す。"""
    return input_dir / f"bigrams_level{level}_n{n_value}.pkl"


def _write_ngrams_cache(
    input_dir: Path,
    level: int,
    n_value: int,
    table: dict[str, dict[int, frozenset]],
) -> Path:
    """n-gram テーブルを pickle で書き出す（tmp → rename のアトミック書き）。

    Args:
        input_dir: abstract JSON があるディレクトリ（cache 配置先）。
        level: 抽象化レベル。
        n_value: n-gram の n。
        table: ``_build_id_to_ngrams_table`` の戻り値。

    Returns:
        書き出した cache のパス。
    """
    cache_path = _ngrams_cache_path(input_dir, level, n_value)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    payload = {
        "version": NGRAMS_CACHE_VERSION,
        "level": level,
        "n": n_value,
        "schema": "abst_id_to_ngrams",
        "data": table,
    }
    with tmp_path.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_path.replace(cache_path)
    print(f"[CACHE] wrote {cache_path}", flush=True)
    return cache_path


def process_level(
    level: int,
    table: dict[str, dict[int, frozenset]],
    output_dir: Path,
    n_value: int,
    tau: float,
    workers: int,
) -> None:
    """1 レベル分を depth ごとに併合し、結果 JSON を書き出す。"""
    level_dir = output_dir / f"level{level}"
    level_dir.mkdir(parents=True, exist_ok=True)

    for depth in DEPTHS:
        ids, sets = _build_patterns_from_table(table, depth)
        classes = greedy_merge(level, ids, sets, n_value, tau, workers)

        out_path = level_dir / f"{depth}.json"
        payload = {
            "meta": {
                "level": level,
                "depth": depth,
                "n": n_value,
                "tau": tau,
                "mode": "jaccard",
                "num_patterns": len(ids),
                "num_classes": len(classes),
            },
            "classes": classes,
        }
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(
            f"[OUTPUT] {out_path}  (patterns={len(ids)} → classes={len(classes)})",
            flush=True,
        )


# ---------------------------------------------------------------------------
# server モード: 転置インデックス + tau 一括 + 候補ペア並列
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
    """候補ペア ``(i, j)`` の Jaccard を計算し ``min_tau`` 以上を返す（index 表現）。

    union サイズは ``len(a) + len(b) - inter`` で求め、和集合オブジェクト生成を
    避ける（結果は ``len(a | b)`` と同一）。
    """
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
    """転置インデックスで「共通 n-gram を持つペア」``(i<j, index)`` を列挙する。

    ``tau > 0`` の Jaccard は共通 n-gram が最低 1 つ必要なため、共通ゼロのペアは
    閾値を超え得ない。全 ``N^2`` ペアではなく共起ペアのみを候補とする厳密な
    絞り込み（近似ではない）。``n-gram が空`` の pattern はここに現れないため、
    呼び出し側で別途まとめる必要がある。

    Returns:
        ``(i, j)``（``i < j``、ids 内インデックス）の重複なしリスト。
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


def _scored_pairs(
    ids: list[str],
    sets: dict[str, frozenset],
    min_tau: float,
    workers: int,
) -> list[tuple[float, str, str]]:
    """候補ペアの類似度を 1 回だけ計算し ``(s, id_a, id_b)`` を返す。

    複数 tau で再利用できるよう ``min_tau`` 以上の候補のみ計算・保持する
    (``s >= min_tau`` を満たさないペアはどの tau でも併合されない)。候補抽出は
    転置インデックス、類似度計算は候補ペアを chunk 分割して並列実行する。
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


def _merge_scored(
    level: int,
    ids: list[str],
    scored: list[tuple[float, str, str]],
    empty_ids: list[str],
    n_value: int,
    tau: float,
) -> dict[str, list[str]]:
    """事前計算済み ``scored`` を ``tau`` でフィルタして貪欲併合する。

    ``empty_ids``（n-gram が空の pattern）は互いに Jaccard=1.0 ≥ tau のため、
    tau に依らず 1 クラスタへ併合する（全ペア版の ``not a and not b → 1.0`` を
    転置インデックス方式で再現する）。
    """
    candidates = [(s, a, b) for s, a, b in scored if s >= tau]
    candidates.sort(key=lambda x: (-x[0], _pair_hash(x[1], x[2])))

    uf = UnionFind(ids)
    for _, a, b in candidates:
        uf.union(a, b)
    for k in range(1, len(empty_ids)):
        uf.union(empty_ids[0], empty_ids[k])

    classes: dict[str, list[str]] = {}
    for _root, members in sorted(uf.components().items(), key=lambda kv: sorted(kv[1])):
        members_sorted = sorted(members)
        class_id = _make_class_id(level, f"jaccard:n{n_value}:{','.join(members_sorted)}")
        classes[class_id] = members_sorted
    return classes


def _tau_dirname(tau: float) -> str:
    """Tau → ``jaccard{NN}`` ディレクトリ名（run.sh 互換: 0.7→jaccard07, 0.9→jaccard09）。"""
    return f"jaccard{round(tau * 10):02d}"


def _write_result(
    out_path: Path,
    level: int,
    depth: str,
    n_value: int,
    tau: float,
    num_patterns: int,
    classes: dict[str, list[str]],
) -> None:
    """1 (tau, level, depth) のクラスタ結果を JSON で書き出す。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "level": level,
            "depth": depth,
            "n": n_value,
            "tau": tau,
            "mode": "jaccard",
            "num_patterns": num_patterns,
            "num_classes": len(classes),
        },
        "classes": classes,
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(
        f"[OUTPUT] {out_path}  (patterns={num_patterns} → classes={len(classes)})",
        flush=True,
    )


def process_level_server(
    level: int,
    table: dict[str, dict[int, frozenset]],
    output_dir: Path,
    n_value: int,
    taus: list[float],
    workers: int,
) -> None:
    """Server モードで 1 レベル分を処理する（depth ごと・複数 tau 一括）。

    各 depth について類似度を ``min(taus)`` で 1 回だけ計算し、各 tau で
    フィルタして ``{output_dir}/jaccard{NN}/level{L}/{depth}.json`` に書き出す。
    """
    min_tau = min(taus)
    for depth in DEPTHS:
        ids, sets = _build_patterns_from_table(table, depth)
        empty_ids = [c for c in ids if not sets[c]]
        scored = _scored_pairs(ids, sets, min_tau, workers)
        for tau in taus:
            classes = _merge_scored(level, ids, scored, empty_ids, n_value, tau)
            out_path = output_dir / _tau_dirname(tau) / f"level{level}" / f"{depth}.json"
            _write_result(out_path, level, depth, n_value, tau, len(ids), classes)


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。"""
    parser = argparse.ArgumentParser(description="approach_minimum integrate: n-gram + Jaccard 貪欲併合")
    parser.add_argument("--input-dir", type=Path, default=None, help="abstract_level{L}.json 置き場")
    parser.add_argument("--output-dir", type=Path, default=None, help="integrate 出力ディレクトリ")
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=[0, 1, 2, 3],
        help="処理する抽象化レベル（入力ファイルが存在するもののみ処理）",
    )
    parser.add_argument("--n", type=int, default=2, help="n-gram の n (default: 2 = bigram)")
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
        help=("server モード: 転置インデックスで候補ペアを厳密に絞り込み、類似度を 1 回だけ計算して複数 tau (--taus) を一括出力する。候補ペア計算を並列化。結果は通常モードと完全一致する。"),
    )
    parser.add_argument(
        "--taus",
        type=float,
        nargs="+",
        default=[0.5, 0.7, 0.9],
        help="server モードで一括処理する Jaccard 閾値群 (default: 0.5 0.7 0.9)",
    )
    return parser.parse_args()


def main() -> None:
    """全レベル・全 depth の貪欲併合を実行する。"""
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
        if not in_path.exists():
            print(f"[SKIP] not found: {in_path}", flush=True)
            continue
        print(f"[INPUT] {in_path}", flush=True)
        with in_path.open(encoding="utf-8") as f:
            records = json.load(f)
        print(f"[RECORDS] level{level}: {len(records)}", flush=True)

        # 1 回だけ全 depth 分の n-gram テーブルを作り、 pickle に書き出す。
        # Representative_value など下流の戦略は abstract JSON を読まずに
        # この cache を消費できる。
        table = _build_id_to_ngrams_table(records, DEPTHS, args.n)
        _write_ngrams_cache(input_dir, level, args.n, table)
        # records は table に取り込み済みのため、 メモリ解放して以降の処理に
        # 影響しないようにする（abstract は数 GB 規模のため）。
        del records

        if args.server:
            process_level_server(level, table, output_dir, args.n, args.taus, workers)
        else:
            process_level(level, table, output_dir, args.n, args.tau, workers)


if __name__ == "__main__":
    main()
