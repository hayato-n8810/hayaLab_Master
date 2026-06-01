"""mb_id ごとの「最小有効サイズ」分布を集計する (Fig./Tab. RQ2-4, Tab. RQ2-5).

各 mb_id について、サイズの小さい順 (Diff → Brother → ExParent → Parent) に
所属クラスを引き、最初に「再現性のあるクラス (size>=2)」に到達したサイズを
``min_effective_size(mb_id)`` と定義する。全 4 サイズが singleton にとどまる
場合は ``"none"`` とラベルする。各 mb_id が持つサイズ集合は cutout の有無に
依存する (一部 mb_id では filtered_out 等で 4 サイズ揃わない) ため、欠落サイズ
は走査時にスキップする。

加えて、以下の派生指標を出す:

* ``redundancy``      — 最小有効サイズより大きいサイズの cutout が「最小有効
                        サイズと同一クラス」に属する割合 (mb_id 単位).
* ``divergence``      — 同 cutout が「最小有効サイズと異なるクラス」に属する
                        割合 (mb_id 単位).
* 各 mb_id 単位の判定を集約した α × M ごとの分布表.

Input: ``outputs/scam/approach_temp_v2_jaccard_tau{tau}/classes_A{n}_M{m}.json``
Output:
  - ``outputs/scam/RQ2/min_effective_size_tau{tau}.json``
  - ``outputs/scam/RQ2/min_effective_size_tau{tau}.csv``  (mb_id 単位 long-form)
  - ``outputs/scam/RQ2/min_effective_size_summary_tau{tau}.csv``  (α × M 分布)

実行例:
    uv run python experiments/scam/RQ2/postproc_min_effective_size.py --tau 0.7
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from experiments.scam.RQ2._common import (  # noqa: E402
    ABST_LEVELS,
    DEPTHS,
    METHODS,
    TAU_VALUES,
    classes_path,
    cutout_to_class,
    load_classes,
    output_dir,
    parse_cutout_id,
    tau_dir,
    write_csv,
    write_json,
)
from hayalab.config import PathConfig  # noqa: E402

# min_effective_size が「集約不可」(全 4 サイズが singleton) であったときの
# ラベル. CSV/集計表で唯一のセンチネル値として用いる.
NONE_LABEL: str = "none"


def _mb_index(cutout_index: dict[str, dict[str, Any]]) -> dict[int, dict[str, dict[str, Any]]]:
    """``{cutout_id: meta}`` を ``{mb_id: {depth: meta}}`` に再構成する."""
    out: dict[int, dict[str, dict[str, Any]]] = {}
    for cutout_id, meta in cutout_index.items():
        mb_id, depth = parse_cutout_id(cutout_id)
        out.setdefault(mb_id, {})[depth] = meta
    return out


def evaluate_mb(per_depth: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """1 mb_id を評価する.

    Args:
        per_depth: ``{depth: {"class_id", "size"}}``. 欠落 depth は dict に
            含まれない.

    Returns:
        ``{
            min_effective_size: str,           # "Diff"/"Brother"/.../"none"
            available_depths: list[str],       # 入力に存在した depth (順序付き)
            class_at_min: str | None,
            sizes_in_class_with_min: dict[depth, bool],
                                               # min_effective_size より大きい
                                               # depth が同一クラスか否か.
            n_redundant: int,
            n_divergent: int,
        }``.
    """
    available = [d for d in DEPTHS if d in per_depth]

    min_size_label: str = NONE_LABEL
    class_at_min: str | None = None
    for depth in available:
        meta = per_depth[depth]
        if meta["size"] >= 2:
            min_size_label = depth
            class_at_min = meta["class_id"]
            break

    sizes_in_class_with_min: dict[str, bool] = {}
    n_redundant = 0
    n_divergent = 0
    if class_at_min is not None:
        # min より「大きい」depth を順次評価する.
        seen_min = False
        for depth in available:
            if not seen_min:
                if depth == min_size_label:
                    seen_min = True
                continue
            same = per_depth[depth]["class_id"] == class_at_min
            sizes_in_class_with_min[depth] = same
            if same:
                n_redundant += 1
            else:
                n_divergent += 1

    return {
        "min_effective_size": min_size_label,
        "available_depths": available,
        "class_at_min": class_at_min,
        "sizes_in_class_with_min": sizes_in_class_with_min,
        "n_redundant": n_redundant,
        "n_divergent": n_divergent,
    }


def aggregate_one(
    classes: list[dict[str, Any]],
) -> dict[str, Any]:
    """1 ファイル (1 つの (τ, α, M) 設定) を mb_id 単位で集計する.

    Args:
        classes: ``classes_A{n}_M{m}.json`` の中身.

    Returns:
        ``{
            "per_mb": {mb_id: evaluate_mb の出力},
            "distribution": {label: count},
            "n_mb": int,
            "redundancy_count": int,   # n_redundant > 0 の mb_id 数
            "divergence_count": int,   # n_divergent > 0 の mb_id 数
        }``.
    """
    cutout_index = cutout_to_class(classes)
    mb_index = _mb_index(cutout_index)
    per_mb: dict[int, dict[str, Any]] = {}
    distribution: Counter[str] = Counter()
    redundancy_count = 0
    divergence_count = 0
    for mb_id in sorted(mb_index):
        ev = evaluate_mb(mb_index[mb_id])
        per_mb[mb_id] = ev
        distribution[ev["min_effective_size"]] += 1
        if ev["n_redundant"] > 0:
            redundancy_count += 1
        if ev["n_divergent"] > 0:
            divergence_count += 1
    return {
        "per_mb": per_mb,
        "distribution": dict(distribution),
        "n_mb": len(per_mb),
        "redundancy_count": redundancy_count,
        "divergence_count": divergence_count,
    }


def run_for_tau(tau: str, pc: PathConfig) -> dict[str, Any]:
    """1 つの τ について全 (α, M) を集計する."""
    root = tau_dir(pc.outputs, tau)
    cells: dict[str, Any] = {}
    for level in ABST_LEVELS:
        for method in METHODS:
            path = classes_path(root, level, method)
            classes = load_classes(path)
            cells[f"A{level}_{method}"] = aggregate_one(classes)
    return {"tau": tau, "cells": cells}


def write_outputs(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path, Path]:
    """JSON / mb 単位 CSV / 分布サマリ CSV を書き出す."""
    tau = result["tau"]
    json_path = out_dir / f"min_effective_size_tau{tau}.json"
    long_csv_path = out_dir / f"min_effective_size_tau{tau}.csv"
    summary_csv_path = out_dir / f"min_effective_size_summary_tau{tau}.csv"

    # JSON: per_mb は mb_id をキーにするので string 化する.
    serializable = {
        "tau": tau,
        "cells": {
            key: {
                "n_mb": cell["n_mb"],
                "distribution": cell["distribution"],
                "redundancy_count": cell["redundancy_count"],
                "divergence_count": cell["divergence_count"],
                "per_mb": {str(k): v for k, v in cell["per_mb"].items()},
            }
            for key, cell in result["cells"].items()
        },
    }
    write_json(json_path, serializable)

    # long-form CSV: tau, level, method, mb_id, min_effective_size, n_redundant, n_divergent
    long_header = (
        "tau",
        "level",
        "method",
        "mb_id",
        "min_effective_size",
        "n_redundant",
        "n_divergent",
    )
    long_rows: list[list[Any]] = []
    for level in ABST_LEVELS:
        for method in METHODS:
            cell = result["cells"][f"A{level}_{method}"]
            for mb_id, ev in cell["per_mb"].items():
                long_rows.append(
                    [
                        tau,
                        level,
                        method,
                        mb_id,
                        ev["min_effective_size"],
                        ev["n_redundant"],
                        ev["n_divergent"],
                    ]
                )
    write_csv(long_csv_path, long_header, long_rows)

    # 分布サマリ: tau, level, method, label, count, ratio
    summary_header = ("tau", "level", "method", "min_effective_size", "count", "ratio")
    summary_rows: list[list[Any]] = []
    all_labels = list(DEPTHS) + [NONE_LABEL]
    for level in ABST_LEVELS:
        for method in METHODS:
            cell = result["cells"][f"A{level}_{method}"]
            n_mb = cell["n_mb"]
            for label in all_labels:
                count = cell["distribution"].get(label, 0)
                ratio = count / n_mb if n_mb else None
                summary_rows.append([tau, level, method, label, count, ratio])
    write_csv(summary_csv_path, summary_header, summary_rows)

    return json_path, long_csv_path, summary_csv_path


def parse_args() -> argparse.Namespace:
    """CLI 引数."""
    parser = argparse.ArgumentParser(description="mb_id ごとの最小有効サイズ集計 (RQ2)")
    parser.add_argument("--tau", choices=TAU_VALUES, default="0.7")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    """エントリポイント."""
    args = parse_args()
    pc = PathConfig()
    out_dir = args.output_dir or output_dir(pc.outputs)
    out_dir.mkdir(parents=True, exist_ok=True)

    targets: list[str] = list(TAU_VALUES) if args.all else [args.tau]
    for tau in targets:
        print(f"[TAU] {tau}", flush=True)
        result = run_for_tau(tau, pc)
        json_path, long_csv, summary_csv = write_outputs(result, out_dir)
        print(f"[OUTPUT] {json_path}", flush=True)
        print(f"[OUTPUT] {long_csv}", flush=True)
        print(f"[OUTPUT] {summary_csv}", flush=True)


if __name__ == "__main__":
    main()
