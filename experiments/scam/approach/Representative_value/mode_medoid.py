r"""戦略 mode_medoid: 各クラスの代表 value を mode + medoid 二段構えで選ぶ。

選択ロジック (``hayalab.scam.representative.representative_for_class``):
    1. クラスメンバーの label value 文字列を集計し、過半数 (support > size/2) を
       占める value があればそれを mode として採用する。
    2. 過半数 mode が無い場合は bigram-Jaccard medoid を採用する。
       medoid は「他メンバーへの Jaccard 平均が最大」のメンバー
       （同点は mb_id 昇順）。
    3. メンバーが 1 件のみの場合はそのまま代表に採用する。

bigram の定義は ``hayalab.scam.cluster.tokens.bigrams_from_nodes``（``integrate.py``
と整合）。 cache pickle 形式は ``hayalab.scam.cluster.jaccard`` の
``NGRAMS_CACHE_*`` で固定される。

入力:
    cluster:  ``outputs/scam/approach/integrate/{tau_dir}/level{L}/{depth}/{depth}.json``
    label:    ``..._label.json``
    abstract: ``outputs/scam/approach/abstract/abstract_level{L}.json``
               （cache: ``bigrams_level{L}_n2.pkl``）

出力:
    ``{tau_dir}/level{L}/{depth}/{depth}_pattern_mode_medoid.json``

スキーマ::

    {
      "meta": {"tau_dir": str, "level": int, "depth": str,
               "strategy": "mode_medoid", "num_classes": int},
      "classes": {
        class_id: {
          "size": int,
          "strategy": "mode" | "medoid" | "single",
          "representative": {"id": int, "value": str},
          "support": int
        }
      }
    }

実行例:
    uv run python experiments/scam/approach/Representative_value/mode_medoid.py \\
        --tau-dir jaccard07 --levels 1
"""

from __future__ import annotations

import argparse
import os
import pickle
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import hayalab
from hayalab.config import PathConfig
from hayalab.scam.cluster.jaccard import (
    NGRAMS_CACHE_SCHEMA,
    NGRAMS_CACHE_VERSION,
    is_cache_fresh,
)
from hayalab.scam.cluster.tokens import DEPTHS, bigrams_from_nodes
from hayalab.scam.representative import representative_for_class

STRATEGY = "mode_medoid"

# ---------------------------------------------------------------------------
# Worker (ProcessPoolExecutor 経由で pickle されるためトップレベル必須)
# ---------------------------------------------------------------------------

# ワーカープロセスが参照する bigram テーブル（initializer で設定）。
_BG: dict[int, frozenset] = {}


def _worker_init(id_to_bigrams: dict[int, frozenset]) -> None:
    """ProcessPoolExecutor initializer として bigram テーブルをワーカーに展開する。

    Args:
        id_to_bigrams: ``mb_id → bigram frozenset`` のテーブル。 worker プロセスごとに
            1 回だけグローバル ``_BG`` に設定し、 以降の ``_class_worker`` から参照する。
    """
    global _BG
    _BG = id_to_bigrams


def _class_worker(item: tuple[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    """1 クラスの代表選択を worker で実行する。

    Args:
        item: ``(class_id, rows)`` ペア。 ``rows`` は ``[{"id": int, "value": str}, ...]``。

    Returns:
        ``(class_id, representative_for_class の結果 dict)``。
    """
    class_id, rows = item
    return class_id, representative_for_class(rows, _BG)


# ---------------------------------------------------------------------------
# I/O ヘルパー（depth × level の組み合わせで複数回呼ばれるため関数化）
# ---------------------------------------------------------------------------


def _load_id_to_bigrams_cached(
    config: PathConfig,
    level: int,
    n_value: int = 2,
) -> dict[str, dict[int, frozenset]] | None:
    """1 レベル分の bigram テーブルをロードする（cache pickle / abstract JSON fallback）。

    1. ``bigrams_level{L}_n{N}.pkl`` が abstract JSON より新しければ pickle を読む
       （[BIGRAMS] cache hit）。
    2. cache が無い・古い・破損なら abstract JSON を読んで ``bigrams_from_nodes`` で
       計算する（[BIGRAMS] cache miss → fallback (json)）。 cache の書き出しは
       行わない（producer は ``integrate.py``）。
    3. cache も abstract JSON も無ければ ``None``。

    Args:
        config: パス解決用の ``PathConfig``。
        level: 抽象化レベル（1 または 2）。
        n_value: n-gram の n（既定 2 = bigram）。

    Returns:
        ``{depth: {mb_id: frozenset(n-grams)}}`` または cache・JSON とも不在なら
        ``None``。
    """
    abs_p = config.outputs / "scam" / "approach" / "abstract" / f"abstract_level{level}.json"
    cache_p = abs_p.with_name(f"bigrams_level{level}_n{n_value}.pkl")

    if is_cache_fresh(cache_p, abs_p):
        with cache_p.open("rb") as f:
            payload = pickle.load(f)  # noqa: S301 -- 自己生成のローカル cache
        if payload.get("version") == NGRAMS_CACHE_VERSION and payload.get("schema") == NGRAMS_CACHE_SCHEMA:
            bigrams = payload.get("bigrams")
            if isinstance(bigrams, dict):
                print(f"[BIGRAMS] cache hit: {cache_p}", flush=True)
                return {d: bigrams.get(d, {}) for d in DEPTHS}
            print("[BIGRAMS] cache missing 'bigrams' field, falling back to JSON", flush=True)
        else:
            print(
                f"[BIGRAMS] cache version mismatch ({payload.get('version')!r}), falling back to JSON",
                flush=True,
            )

    if not abs_p.exists():
        return None

    print(f"[BIGRAMS] cache miss → fallback to {abs_p}", flush=True)
    records = hayalab.read_json(str(abs_p))
    table: dict[str, dict[int, frozenset]] = {d: {} for d in DEPTHS}
    for entry in records:
        mb_id = entry["id"]
        cutouts = entry.get("cutouts", {})
        for depth in DEPTHS:
            cutout = cutouts.get(depth)
            if not cutout:
                continue
            table[depth][mb_id] = bigrams_from_nodes(cutout.get("nodes", []))
    return table


def _read_label(config: PathConfig, tau_dir: str, level: int, depth: str) -> dict[str, list[dict[str, Any]]] | None:
    """``{depth}_label.json`` を読み、無ければ ``None`` を返す。

    cluster JSON は class_id の集合を含むだけで、 メンバーごとの ``{id, value}`` 列は
    label JSON が持つ。 mode_medoid は label のみ参照する。

    Args:
        config: パス解決用の ``PathConfig``。
        tau_dir: ``integrate`` 配下の tau ディレクトリ名（例 ``"jaccard07"``）。
        level: 抽象化レベル。
        depth: 対象 depth（``Diff`` / ``Brother`` / ``ExParent`` / ``Parent``）。

    Returns:
        ``{class_id: [{"id": int, "value": str}, ...]}``。 label JSON が無ければ
        ``None``。
    """
    label_p = config.outputs / "scam" / "approach" / "integrate" / tau_dir / f"level{level}" / depth / f"{depth}_label.json"
    if not label_p.exists():
        return None
    return hayalab.read_json(str(label_p))


def _write_output(config: PathConfig, tau_dir: str, level: int, depth: str, payload: dict[str, Any]) -> Path:
    """戦略別出力 JSON を書き出してパスを返す。

    Args:
        config: パス解決用の ``PathConfig``。
        tau_dir: ``integrate`` 配下の tau ディレクトリ名。
        level: 抽象化レベル。
        depth: 対象 depth。
        payload: 書き出す JSON dict（``{"meta": ..., "classes": ...}``）。

    Returns:
        書き出した JSON ファイルの絶対パス。
    """
    out = config.outputs / "scam" / "approach" / "integrate" / tau_dir / f"level{level}" / depth / f"{depth}_pattern_{STRATEGY}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    hayalab.write_json(str(out), payload)
    return out


def _run_parallel(
    items: list[Any],
    worker_fn: Callable[[Any], Any],
    workers: int,
    initializer: Callable[..., None],
    initargs: tuple,
    chunksize: int = 64,
) -> list[Any]:
    """``items`` を ``worker_fn`` で並列処理し、入力順を保った結果リストを返す。

    ``workers <= 1`` または ``len(items) < 2`` のときは逐次実行（このときも
    ``initializer`` を呼んでワーカーグローバルを整え、 逐次・並列で挙動を揃える）。

    ``ProcessPoolExecutor.map(items, chunksize)`` を用いるため結果は入力順で並ぶ。
    これにより並列実行でも出力 JSON が byte-identical になる（``dict(results)`` の
    class_id 順が安定する）。

    Args:
        items: 1 タスクに渡す入力の列。 各要素は pickle 可能であること。
        worker_fn: module-level の callable（pickle 可能、ローカル関数不可）。
        workers: 並列ワーカー数。``<= 1`` なら逐次実行。
        initializer: 各ワーカープロセス起動時に 1 回呼ばれる初期化関数。
        initargs: ``initializer`` へ渡す引数タプル。
        chunksize: ``ProcessPoolExecutor.map`` のチャンクサイズ。

    Returns:
        ``[worker_fn(item) for item in items]`` と同順の結果リスト。
    """
    if workers <= 1 or len(items) < 2:
        initializer(*initargs)
        return [worker_fn(it) for it in items]
    with ProcessPoolExecutor(max_workers=workers, initializer=initializer, initargs=initargs) as ex:
        return list(ex.map(worker_fn, items, chunksize=chunksize))


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。

    Returns:
        argparse の ``Namespace``。フィールドは ``tau_dir`` / ``levels`` / ``depths``
        / ``workers``。
    """
    p = argparse.ArgumentParser(description="戦略 mode_medoid: 各クラスの代表 value を mode + medoid で選ぶ")
    p.add_argument("--tau-dir", type=str, default="jaccard07")
    p.add_argument("--levels", type=int, nargs="+", default=[1, 2])
    p.add_argument("--depths", type=str, nargs="+", default=list(DEPTHS))
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列ワーカー数 (default: os.cpu_count())。1 で逐次実行",
    )
    return p.parse_args()


def main() -> None:
    """全 level × 全 depth に対し代表化を実行する。

    各 level で bigram テーブルをロードし、 4 つの depth について label JSON を読んで
    クラスごとの代表 value を ``_class_worker`` で並列計算する。 結果は
    ``{depth}_pattern_mode_medoid.json`` に書き出す。 level 切り替え時に bigram テーブルを
    破棄してピークメモリを抑制する。
    """
    args = parse_args()
    config = PathConfig()
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)
    print(f"[CONFIG] workers={workers}", flush=True)

    for level in args.levels:
        table = _load_id_to_bigrams_cached(config, level)
        if table is None:
            print(f"[SKIP] level{level}: bigrams cache and abstract JSON both missing", flush=True)
            continue

        for depth in args.depths:
            id_to_bigrams = table.get(depth, {})

            # label JSON を読み、 class_id 順を維持しつつ各クラス代表を並列構築する。
            label = _read_label(config, args.tau_dir, level, depth)
            if label is None:
                print(f"[SKIP] {args.tau_dir}/level{level}/{depth}: label missing", flush=True)
                continue

            items = list(label.items())
            results = _run_parallel(
                items,
                _class_worker,
                workers,
                initializer=_worker_init,
                initargs=(id_to_bigrams,),
            )
            classes: dict[str, dict[str, Any]] = dict(results)

            payload = {
                "meta": {
                    "tau_dir": args.tau_dir,
                    "level": level,
                    "depth": depth,
                    "strategy": STRATEGY,
                    "num_classes": len(classes),
                },
                "classes": classes,
            }
            out = _write_output(config, args.tau_dir, level, depth, payload)
            print(f"[OUTPUT] {out}  (classes={len(classes)})", flush=True)

        # peak メモリを抑えるため、 次 level に進む前に table を解放する。
        del table


if __name__ == "__main__":
    main()
