"""approach 統合: bigram complete-linkage + unigram 完全一致 grouping.

処理概要:

1. 入力 ``abstract_level{L}.json`` を読み込む。
2. Diff / Brother / ExParent / Parent の各 depth について、 cutout の有効
   トークン列 (``variadic=True`` を除外したノード列) の長さ ``n_t`` で振り分ける。

   * ``n_t == 0``: 除外（クラスタ生成対象外）。 cutout は存在するが
     全ノードが variadic で抽象化後に有効トークンが残らないケース。
   * ``0 < n_t < n``: unigram 完全一致で grouping。
   * ``n_t >= n``: bigram Jaccard complete-linkage（クラスタ内任意の 2 メンバーが Jaccard ≥ tau）。

3. depth ごとに「bigram クラスタ」+「unigram クラスタ」を 1 つの ``classes``
   辞書に統合して JSON で書き出す。 ``class_id`` の prefix で由来を判別できる
   (``L*_M2_*``: bigram, ``L*_U1_*``: unigram)。

入力:
    outputs/scam/approach/abstract/abstract_level{1,2}.json
    （cache: bigrams_level{L}_n{N}.pkl）

出力:
    outputs/scam/approach/integrate/jaccard{NN}/level{L}/{depth}/{depth}.json

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

Cache pickle (v2):
    outputs/scam/approach/abstract/bigrams_level{L}_n{N}.pkl
    {
        "version": 2,
        "schema": "abst_id_to_features_v2",
        "level": L,
        "n": N,
        "bigrams":  {depth: {mb_id: frozenset(bigrams)}},
        "unigrams": {depth: {mb_id: tuple(tokens)}},
        "excluded": {depth: int},
    }

実行例:
    uv run python experiments/scam/approach/integrate.py --taus 0.7 0.9 --workers 40
    uv run python experiments/scam/approach/integrate.py --levels 1 --taus 0.7
"""

from __future__ import annotations

import argparse
import os
import pickle
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import hayalab
from hayalab.scam.cluster.jaccard import (
    NGRAMS_CACHE_SCHEMA,
    NGRAMS_CACHE_VERSION,
    is_cache_fresh,
)
from hayalab.scam.cluster.linkage import (
    build_bigram_patterns,
    candidate_pairs,
    complete_merge_bigrams,
    extract_features,
    group_identical,
    group_unigrams,
    make_chunks,
)
from hayalab.scam.cluster.tokens import DEPTHS

# ---------------------------------------------------------------------------
# Worker (ProcessPoolExecutor 経由で pickle されるためトップレベル必須)
# ---------------------------------------------------------------------------

# 候補ペア類似度計算ワーカーが参照するグローバル（index → n-gram 集合）。
_SIM_SETS: list[frozenset] = []


def _sim_worker_init(sets_list: list[frozenset]) -> None:
    """ProcessPoolExecutor initializer: index → n-gram 集合をワーカーに展開する。"""
    global _SIM_SETS
    _SIM_SETS = sets_list


def _score_pair_chunk(
    pairs: list[tuple[int, int]],
    min_tau: float,
) -> list[tuple[float, int, int]]:
    """候補ペア ``(i, j)`` の Jaccard を計算し ``min_tau`` 以上を返す（index 表現）。

    ProcessPoolExecutor のワーカーから呼ばれる。
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


# ---------------------------------------------------------------------------
# Cache I/O（level ごとに 2 回呼ばれるため関数化）
# ---------------------------------------------------------------------------


def _features_cache_path(input_dir: Path, level: int, n_value: int) -> Path:
    """Features cache pickle のパスを返す。"""
    return input_dir / f"bigrams_level{level}_n{n_value}.pkl"


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
# 出力 I/O（depth × tau の組合せ分繰り返し呼ばれるため関数化）
# ---------------------------------------------------------------------------


def _tau_dirname(tau: float) -> str:
    """Tau → ``jaccard{NN}`` ディレクトリ名（0.7 → jaccard07, 0.9 → jaccard09）。"""
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
# CLI / main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="approach integrate (complete-linkage): bigram complete-linkage + unigram 完全一致 grouping (len=0 cutouts は除外)",
    )
    parser.add_argument("--input-dir", type=Path, default=None, help="abstract_level{L}.json 置き場")
    parser.add_argument("--output-dir", type=Path, default=None, help="integrate 出力ディレクトリ")
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=[1, 2],
        help="処理する抽象化レベル（入力ファイルが存在するもののみ処理）",
    )
    parser.add_argument(
        "--n",
        type=int,
        default=2,
        help="n-gram の n (default: 2 = bigram)",
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
        help="features cache pickle を生成・更新する。未指定なら読むのみ。",
    )
    return parser.parse_args()


def main() -> None:
    """全レベル・全 depth の complete-linkage 統合を実行する。"""
    path_config = hayalab.config.PathConfig()
    args = parse_args()

    input_dir = args.input_dir or (path_config.outputs / "scam" / "approach" / "abstract")
    output_dir = args.output_dir or (path_config.outputs / "scam" / "approach" / "integrate")
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)

    print(
        f"[CONFIG] MODE=complete-linkage n={args.n} taus={args.taus} workers={workers} levels={args.levels}",
        flush=True,
    )

    for level in args.levels:
        in_path = input_dir / f"abstract_level{level}.json"
        cache_path = _features_cache_path(input_dir, level, args.n)

        # features (bigrams/unigrams/excluded) を取得: cache → JSON fallback
        features: tuple[dict, dict, dict] | None = None
        if not args.create_cache and is_cache_fresh(cache_path, in_path):
            try:
                features = _load_features_cache(cache_path)
                print(f"[CACHE] fresh, loading from pickle: {cache_path}", flush=True)
            except (ValueError, pickle.UnpicklingError, EOFError) as e:
                print(f"[CACHE] load failed ({e}), falling back to JSON", flush=True)
                features = None

        if features is None:
            if not in_path.exists():
                print(f"[SKIP] not found: {in_path}", flush=True)
                continue
            print(f"[INPUT] {in_path}", flush=True)
            records = hayalab.read_json(in_path)
            print(f"[RECORDS] level{level}: {len(records)}", flush=True)
            features = extract_features(records, DEPTHS, args.n)
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

        # depth × tau の complete-linkage 統合（並列スコアリングは tau 非依存で 1 回）
        min_tau = min(args.taus)
        for depth in DEPTHS:
            ids, sets = build_bigram_patterns(bigrams_table, depth)
            unigrams_d = unigrams_table.get(depth, {})
            excluded_d = excluded_table.get(depth, 0)

            # tau 非依存パート: unigram grouping + 完全一致グルーピング + 候補類似度
            unigram_classes = group_unigrams(level, depth, unigrams_d)
            rep_ids, rep_sets, rep_members = group_identical(ids, sets)

            # 候補ペアの類似度を min_tau 以上で並列計算（複数 tau で再利用）
            sets_list = [rep_sets[c] for c in rep_ids]
            pairs = candidate_pairs(rep_ids, rep_sets)
            scored: list[tuple[float, str, str]] = []
            if pairs:
                if workers <= 1 or len(pairs) < workers * 2:
                    _sim_worker_init(sets_list)
                    scored_idx = _score_pair_chunk(pairs, min_tau)
                else:
                    chunks = make_chunks(len(pairs), max(workers * 4, 1))
                    scored_idx = []
                    with ProcessPoolExecutor(
                        max_workers=workers,
                        initializer=_sim_worker_init,
                        initargs=(sets_list,),
                    ) as ex:
                        futures = [ex.submit(_score_pair_chunk, pairs[i0:i1], min_tau) for i0, i1 in chunks]
                        for fut in as_completed(futures):
                            scored_idx.extend(fut.result())
                scored = [(s, rep_ids[i], rep_ids[j]) for s, i, j in scored_idx]

            print(
                f"[GROUP] level{level} {depth}: patterns={len(ids)} reps={len(rep_ids)} scored_pairs={len(scored)}",
                flush=True,
            )

            # tau ごとに complete-linkage 併合と書き出し
            for tau in args.taus:
                bigram_classes = complete_merge_bigrams(level, rep_ids, rep_members, scored, args.n, tau)
                out_path = output_dir / _tau_dirname(tau) / f"level{level}" / f"{depth}" / f"{depth}.json"
                _write_result(
                    out_path,
                    level,
                    depth,
                    args.n,
                    tau,
                    len(ids),
                    len(unigrams_d),
                    excluded_d,
                    bigram_classes,
                    unigram_classes,
                )


if __name__ == "__main__":
    main()
