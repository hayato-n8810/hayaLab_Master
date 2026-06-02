r"""戦略 2: クラス内 bigram の intersection を抽出して代表とする.

クラスを生成した類似度（n-gram + Jaccard）の根拠そのものを保存する。すなわち
クラスの全メンバーが共有する bigram 集合 ``∩_i bigrams(member_i)`` を取り、
クラスの「核」を bigram のリストとして提示する。

戦略の特徴:
    * 推移併合の影響を受けにくい（外れ値メンバーが 1 つでも該当 bigram を
      持たなければ intersection から落ちる）。
    * トークン列としての再構成は意図的にしない（Eulerian 化は破壊的になり得る
      ため、後段で別途行う）。
    * 同時に medoid もメタ情報として記録し、人間が読む際の手がかりを残す。

bigram 定義は ``integrate.py`` と同一。

入力:
    cluster:  ``outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}.json``
    label:    ``..._label.json``（class_id 順の保存に利用）
    abstract: ``outputs/scam/approach_minimum/abstract/abstract_level{L}.json``

出力:
    ``{tau_dir}/level{L}/{depth}_pattern_common_bigrams.json``

スキーマ::

    {
      "meta": {"tau_dir": str, "level": int, "depth": str,
                "strategy": "common_bigrams", "num_classes": int},
      "classes": {
        class_id: {
          "size": int,
          "common_count": int,
          "common_bigrams": [[[name, value], [name, value]], ...],
          "medoid_id": int   // 参考: bigram-Jaccard medoid の mb_id
        }
      }
    }

bigram は ``[[name, value], [name, value]]`` 形式（JSON 互換）で出力する。

実行例:
    uv run python experiments/scam/approach_minimum/Representative_value/common_bigrams.py \\
        --tau-dir jaccard07 --levels 0
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from _common import (
    DEPTHS,
    jaccard,
    load_id_to_bigrams_cached,
    read_inputs,
    run_parallel,
    write_output,
)

from hayalab.config import PathConfig

STRATEGY = "common_bigrams"

# ワーカープロセスが参照する bigram テーブル（initializer で設定）。
_BG: dict[int, frozenset] = {}


def _worker_init(id_to_bigrams: dict[int, frozenset]) -> None:
    """ProcessPoolExecutor initializer: bigram テーブルをワーカーに展開する."""
    global _BG
    _BG = id_to_bigrams


def _class_worker(item: tuple[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    """1 クラスの共通 bigram 抽出 + medoid 算出をワーカーで実行する."""
    class_id, rows = item
    member_ids = [r["id"] for r in rows]
    return class_id, _class_payload(member_ids, _BG)


def _intersect_bigrams(member_ids: list[int], id_to_bigrams: dict[int, frozenset]) -> frozenset:
    """メンバー全員に共通する bigram 集合を返す."""
    if not member_ids:
        return frozenset()
    common: frozenset | None = None
    for mid in member_ids:
        bg = id_to_bigrams.get(mid, frozenset())
        common = bg if common is None else (common & bg)
        if not common:
            return frozenset()
    return common or frozenset()


def _pick_medoid_id(member_ids: list[int], id_to_bigrams: dict[int, frozenset]) -> int:
    """bigram-Jaccard 平均が最大のメンバー id（同点は id 昇順）."""
    sets = [(mid, id_to_bigrams.get(mid, frozenset())) for mid in member_ids]
    if len(sets) == 1:
        return sets[0][0]
    best: tuple[float, int] | None = None
    for i, (mid_i, s_i) in enumerate(sets):
        total = sum(jaccard(s_i, s_j) for j, (_mid_j, s_j) in enumerate(sets) if j != i)
        avg = total / (len(sets) - 1)
        key = (-avg, mid_i)
        if best is None or key < (-best[0], best[1]):
            best = (avg, mid_i)
    assert best is not None
    return best[1]


def _bigram_to_json(bigram: tuple[tuple[str, str], tuple[str, str]]) -> list[list[str]]:
    """``((name,val),(name,val))`` → ``[[name,val],[name,val]]`` (JSON 互換).

    決定的順序のため、呼び出し側で集合をソート済みである前提。
    """
    return [list(bigram[0]), list(bigram[1])]


def _class_payload(
    member_ids: list[int],
    id_to_bigrams: dict[int, frozenset],
) -> dict[str, Any]:
    """1 クラス分の payload を作る."""
    common = _intersect_bigrams(member_ids, id_to_bigrams)
    sorted_bigrams = sorted(common)  # tuple の自然順序で安定化
    return {
        "size": len(member_ids),
        "common_count": len(common),
        "common_bigrams": [_bigram_to_json(b) for b in sorted_bigrams],
        "medoid_id": _pick_medoid_id(member_ids, id_to_bigrams),
    }


def process_depth(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
    id_to_bigrams: dict[int, frozenset],
    workers: int,
) -> None:
    """1 (tau_dir, level, depth) を処理する."""
    _cluster, label = read_inputs(config, tau_dir, level, depth)
    if label is None:
        print(f"[SKIP] {tau_dir}/level{level}/{depth}: missing input", flush=True)
        return

    items = list(label.items())
    results = run_parallel(
        items,
        _class_worker,
        workers,
        initializer=_worker_init,
        initargs=(id_to_bigrams,),
    )
    classes: dict[str, dict[str, Any]] = dict(results)

    payload = {
        "meta": {
            "tau_dir": tau_dir,
            "level": level,
            "depth": depth,
            "strategy": STRATEGY,
            "num_classes": len(classes),
        },
        "classes": classes,
    }
    out = write_output(config, tau_dir, level, depth, STRATEGY, payload)
    print(f"[OUTPUT] {out}  (classes={len(classes)})", flush=True)


def parse_args() -> argparse.Namespace:
    """CLI 引数."""
    p = argparse.ArgumentParser(description="戦略 common_bigrams: クラス内 bigram intersection を代表とする")
    p.add_argument("--tau-dir", type=str, default="jaccard07")
    p.add_argument("--levels", type=int, nargs="+", default=[0, 1, 2, 3])
    p.add_argument("--depths", type=str, nargs="+", default=list(DEPTHS))
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列ワーカー数 (default: os.cpu_count())。1 で逐次実行",
    )
    return p.parse_args()


def main() -> None:
    """全 level × 全 depth で代表化を実行する."""
    args = parse_args()
    config = PathConfig()
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)
    print(f"[CONFIG] workers={workers}", flush=True)

    for level in args.levels:
        table = load_id_to_bigrams_cached(config, level)
        if table is None:
            print(
                f"[SKIP] level{level}: bigrams cache and abstract JSON both missing",
                flush=True,
            )
            continue

        for depth in args.depths:
            id_to_bigrams = table.get(depth, {})
            process_depth(config, args.tau_dir, level, depth, id_to_bigrams, workers)
        del table


if __name__ == "__main__":
    main()
