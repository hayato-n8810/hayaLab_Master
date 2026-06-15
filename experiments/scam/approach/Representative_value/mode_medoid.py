r"""戦略 1: mode + medoid 二段構えで各クラスの代表 value を選ぶ.

選択ロジック:
    1. クラスメンバーの label value 文字列を集計し、過半数 (support > size/2) を
       占める value があればそれを mode として採用する。
    2. 過半数 mode が無い場合は bigram-Jaccard medoid を採用する。medoid は
       「他メンバーへの Jaccard 平均が最大」のメンバー（同点は mb_id 昇順）。
    3. メンバーが 1 件のみの場合はそのまま代表に採用する。

bigram の定義は ``integrate.py`` と完全に同一（``_common.bigrams_from_nodes``）。

入力:
    cluster:  ``outputs/scam/approach/integrate/{tau_dir}/level{L}/{depth}/{depth}.json``
    label:    ``..._label.json``
    abstract: ``outputs/scam/approach/abstract/abstract_level{L}.json``

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
          "support": int   // mode の場合、その value を持つメンバー数
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
from collections import Counter
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

STRATEGY = "mode_medoid"

# ワーカープロセスが参照する bigram テーブル（initializer で設定）。
_BG: dict[int, frozenset] = {}


def _worker_init(id_to_bigrams: dict[int, frozenset]) -> None:
    """ProcessPoolExecutor initializer: bigram テーブルをワーカーに展開する."""
    global _BG
    _BG = id_to_bigrams


def _class_worker(item: tuple[str, list[dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    """1 クラスの代表選択をワーカーで実行する."""
    class_id, rows = item
    return class_id, _representative_for_class(rows, _BG)


def _pick_mode(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], int] | None:
    """Value の過半数 mode を返す。無ければ ``None``.

    Args:
        rows: ``[{"id": int, "value": str}, ...]``。

    Returns:
        ``(代表 row, support)`` または過半数 mode が無いとき ``None``。
        同 value の中で id 最小のものを代表に採る（決定性確保）。
    """
    counts = Counter(r["value"] for r in rows)
    value, support = counts.most_common(1)[0]
    if support * 2 <= len(rows):  # 過半数条件: support > size / 2
        return None
    # 同 value 内で id 最小を代表
    cands = [r for r in rows if r["value"] == value]
    representative = min(cands, key=lambda r: r["id"])
    return representative, support


def _pick_medoid(
    rows: list[dict[str, Any]],
    id_to_bigrams: dict[int, frozenset],
) -> dict[str, Any]:
    """bigram-Jaccard 平均が最大のメンバーを返す。同点は ``id`` 昇順.

    Args:
        rows: クラスメンバー（``{"id", "value"}``）。
        id_to_bigrams: mb_id → bigram frozenset。

    Returns:
        代表 row。
    """
    sets = [(r, id_to_bigrams.get(r["id"], frozenset())) for r in rows]
    best: tuple[float, int, dict[str, Any]] | None = None
    for r_i, s_i in sets:
        total = sum(jaccard(s_i, s_j) for r_j, s_j in sets if r_j["id"] != r_i["id"])
        avg = total / max(len(sets) - 1, 1)
        key = (-avg, r_i["id"])  # 平均降順、id 昇順
        if best is None or key < (-best[0], best[1]):
            best = (avg, r_i["id"], r_i)
    assert best is not None
    return best[2]


def _representative_for_class(
    rows: list[dict[str, Any]],
    id_to_bigrams: dict[int, frozenset],
) -> dict[str, Any]:
    """1 クラスに対する代表選択結果を作る."""
    size = len(rows)
    if size == 1:
        r = rows[0]
        return {
            "size": 1,
            "strategy": "single",
            "representative": {"id": r["id"], "value": r["value"]},
            "support": 1,
        }

    mode_res = _pick_mode(rows)
    if mode_res is not None:
        rep, support = mode_res
        return {
            "size": size,
            "strategy": "mode",
            "representative": {"id": rep["id"], "value": rep["value"]},
            "support": support,
        }

    rep = _pick_medoid(rows, id_to_bigrams)
    return {
        "size": size,
        "strategy": "medoid",
        "representative": {"id": rep["id"], "value": rep["value"]},
        "support": sum(1 for r in rows if r["value"] == rep["value"]),
    }


def process_depth(
    config: PathConfig,
    tau_dir: str,
    level: int,
    depth: str,
    id_to_bigrams: dict[int, frozenset],
    workers: int,
) -> None:
    """1 (tau_dir, level, depth) を処理し代表 JSON を書き出す."""
    _cluster, label = read_inputs(config, tau_dir, level, depth)
    if label is None:
        print(f"[SKIP] {tau_dir}/level{level}/{depth}: cluster or label missing", flush=True)
        return

    # label JSON の class_id 順を維持しつつ各クラス代表を並列構築。
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
    """全 level × 全 depth に対し代表化を実行する."""
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
        # peak メモリを抑えるため、 次 level に進む前に table を解放する。
        del table


if __name__ == "__main__":
    main()
