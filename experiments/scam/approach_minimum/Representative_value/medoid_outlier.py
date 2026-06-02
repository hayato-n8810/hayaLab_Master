r"""戦略 4: medoid 代表 + 外れ値メンバー分離.

クラスの medoid（他メンバーへの bigram-Jaccard 平均が最大のメンバー）を代表に
採用しつつ、 medoid からの Jaccard が ``--outlier-tau`` 未満のメンバーを
「外れメンバー」として別ラベルに切り出す。

ねらい:
    integrate の greedy union-find は推移的に併合するため、

        A ─0.9─ B ─0.8─ C

    のような連鎖で A と C が同一クラスに入る（A-C 自身の Jaccard は低くても可）。
    医domain (=medoid) 中心の球を半径 ``outlier_tau`` で切ると、こうした
    周縁メンバーを可視化できる。クラスを分割するのではなく、注釈として外れ
    メンバーを列挙する点に注意（後段で本格的なサブクラスタリングを行うなら
    別途実装する）。

入力:
    cluster:  ``outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}.json``
    label:    ``..._label.json``
    abstract: ``outputs/scam/approach_minimum/abstract/abstract_level{L}.json``

出力:
    ``{tau_dir}/level{L}/{depth}_pattern_medoid_outlier.json``

スキーマ::

    {
      "meta": {"tau_dir", "level", "depth",
                "strategy": "medoid_outlier",
                "outlier_tau": float, "num_classes": int},
      "classes": {
        class_id: {
          "size": int,
          "representative": {"id": int, "value": str, "avg_jaccard": float},
          "core_ids": [int, ...],     // medoid からの Jaccard が outlier_tau 以上
          "outliers": [
            {"id": int, "value": str, "jaccard_to_medoid": float}, ...
          ]
        }
      }
    }

``representative.id`` は ``core_ids`` に必ず含まれる（自己 Jaccard = 1.0 のため）。

実行例:
    uv run python experiments/scam/approach_minimum/Representative_value/medoid_outlier.py \\
        --tau-dir jaccard07 --outlier-tau 0.5 --levels 0
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from _common import (
    DEPTHS,
    abstract_path,
    jaccard,
    load_id_to_bigrams,
    read_inputs,
    run_parallel,
    write_output,
)

import hayalab
from hayalab.config import PathConfig

STRATEGY = "medoid_outlier"

# ワーカープロセスが参照する bigram テーブルと outlier_tau（initializer で設定）。
_BG: dict[int, frozenset] = {}
_OUTLIER_TAU: float = 0.5


def _worker_init(id_to_bigrams: dict[int, frozenset], outlier_tau: float) -> None:
    """ProcessPoolExecutor initializer: bigram テーブルと閾値をワーカーに展開."""
    global _BG, _OUTLIER_TAU
    _BG = id_to_bigrams
    _OUTLIER_TAU = outlier_tau


def _class_worker(item: tuple[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    """1 クラスの medoid 抽出 + 外れ値分離をワーカーで実行する."""
    class_id, rows = item
    return class_id, _class_payload(rows, _BG, _OUTLIER_TAU)


def _medoid_and_avg(
    rows: list[dict[str, Any]],
    id_to_bigrams: dict[int, frozenset],
) -> tuple[dict[str, Any], float]:
    """Medoid row と他メンバーへの平均 Jaccard を返す.

    1 メンバーのクラスでは平均は 1.0 とみなす（自己類似度のみ）。
    """
    if len(rows) == 1:
        return rows[0], 1.0

    sets = [(r, id_to_bigrams.get(r["id"], frozenset())) for r in rows]
    best: tuple[float, int, dict[str, Any]] | None = None
    for i, (r_i, s_i) in enumerate(sets):
        total = sum(jaccard(s_i, s_j) for j, (_r_j, s_j) in enumerate(sets) if j != i)
        avg = total / (len(sets) - 1)
        key = (-avg, r_i["id"])  # 平均降順、id 昇順
        if best is None or key < (-best[0], best[1]):
            best = (avg, r_i["id"], r_i)
    assert best is not None
    return best[2], best[0]


def _partition_core_outliers(
    medoid_id: int,
    rows: list[dict[str, Any]],
    id_to_bigrams: dict[int, frozenset],
    outlier_tau: float,
) -> tuple[list[int], list[dict[str, Any]]]:
    """Medoid からの Jaccard で core / outliers に分離する.

    Returns:
        ``(core_ids, outliers)``。core_ids は medoid を含み、 id 昇順。
        outliers は Jaccard 昇順（外れ度合いが大きい順）、同値時は id 昇順。
    """
    medoid_set = id_to_bigrams.get(medoid_id, frozenset())
    core_ids: list[int] = []
    outliers: list[dict[str, Any]] = []
    for r in rows:
        if r["id"] == medoid_id:
            core_ids.append(r["id"])
            continue
        sim = jaccard(medoid_set, id_to_bigrams.get(r["id"], frozenset()))
        if sim >= outlier_tau:
            core_ids.append(r["id"])
        else:
            outliers.append({"id": r["id"], "value": r["value"], "jaccard_to_medoid": sim})
    core_ids.sort()
    outliers.sort(key=lambda d: (d["jaccard_to_medoid"], d["id"]))
    return core_ids, outliers


def _class_payload(
    rows: list[dict[str, Any]],
    id_to_bigrams: dict[int, frozenset],
    outlier_tau: float,
) -> dict[str, Any]:
    """1 クラス分の代表 + 外れ値分離結果を返す."""
    medoid, avg = _medoid_and_avg(rows, id_to_bigrams)
    core_ids, outliers = _partition_core_outliers(medoid["id"], rows, id_to_bigrams, outlier_tau)
    return {
        "size": len(rows),
        "representative": {
            "id": medoid["id"],
            "value": medoid["value"],
            "avg_jaccard": avg,
        },
        "core_ids": core_ids,
        "outliers": outliers,
    }


def process_depth(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
    id_to_bigrams: dict[int, frozenset],
    outlier_tau: float,
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
        initargs=(id_to_bigrams, outlier_tau),
    )
    classes: dict[str, dict[str, Any]] = dict(results)

    payload = {
        "meta": {
            "tau_dir": tau_dir,
            "level": level,
            "depth": depth,
            "strategy": STRATEGY,
            "outlier_tau": outlier_tau,
            "num_classes": len(classes),
        },
        "classes": classes,
    }
    out = write_output(config, tau_dir, level, depth, STRATEGY, payload)
    print(f"[OUTPUT] {out}  (classes={len(classes)})", flush=True)


def parse_args() -> argparse.Namespace:
    """CLI 引数."""
    p = argparse.ArgumentParser(description="戦略 medoid_outlier: medoid 代表 + 外れメンバー分離")
    p.add_argument("--tau-dir", type=str, default="jaccard07")
    p.add_argument("--levels", type=int, nargs="+", default=[0, 1, 2, 3])
    p.add_argument("--depths", type=str, nargs="+", default=list(DEPTHS))
    p.add_argument(
        "--outlier-tau",
        type=float,
        default=0.5,
        help="medoid からの Jaccard がこの値未満なら外れメンバー扱い (default: 0.5)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="並列ワーカー数 (default: os.cpu_count())。1 で逐次実行",
    )
    return p.parse_args()


def main() -> None:
    """全 level × 全 depth で代表 + 外れ値分離を実行する."""
    args = parse_args()
    config = PathConfig()
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)
    print(f"[CONFIG] workers={workers}", flush=True)

    for level in args.levels:
        abs_path = abstract_path(config, level)
        if not abs_path.exists():
            print(f"[SKIP] abstract not found: {abs_path}", flush=True)
            continue
        print(f"[ABSTRACT] {abs_path}", flush=True)
        records = hayalab.read_json(str(abs_path))

        for depth in args.depths:
            id_to_bigrams = load_id_to_bigrams(records, depth)
            process_depth(config, args.tau_dir, level, depth, id_to_bigrams, args.outlier_tau, workers)


if __name__ == "__main__":
    main()
