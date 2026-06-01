"""α × σ クロス表 (Tab. RQ2-2a / 2b) を生成する.

各 (τ, α, M, σ) について以下を集計する.

* ``n_cutouts``                 — サイズ σ に属する cutout の総数.
* ``n_singletons``              — そのうち singleton クラス (size==1) に
                                  属する cutout の数.
* ``singleton_ratio``           — ``n_singletons / n_cutouts``.
* ``mean_class_size``           — サイズ σ に属する cutout が所属するクラスの
                                  平均サイズ.
* ``median_class_size``         — 同中央値.
* ``survival_count``            — そのうち再現性のあるクラス (size >= 2) に
                                  属する cutout の数.
* ``survival_ratio``            — ``survival_count / n_cutouts``.

Input: ``outputs/scam/approach_temp_v2_jaccard_tau{tau}/classes_A{n}_M{m}.json``
Output:
  - ``outputs/scam/RQ2/alpha_sigma_grid_tau{tau}.json``
  - ``outputs/scam/RQ2/alpha_sigma_grid_tau{tau}.csv``

実行例:
    uv run python experiments/scam/RQ2/postproc_alpha_sigma_grid.py --tau 0.7
    uv run python experiments/scam/RQ2/postproc_alpha_sigma_grid.py --all
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Any

# experiments パッケージは pyproject.toml に登録されていないため、
# repo root を sys.path に追加して ``from experiments...`` を解決する.
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


def aggregate_one(
    classes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """1 ファイル (1 つの (τ, α, M) 設定) を σ 別に集計する.

    Args:
        classes: ``classes_A{n}_M{m}.json`` の中身.

    Returns:
        ``{depth: {n_cutouts, n_singletons, singleton_ratio, mean_class_size,
        median_class_size, survival_count, survival_ratio}}``.
    """
    per_depth_sizes: dict[str, list[int]] = {d: [] for d in DEPTHS}
    cutout_index = cutout_to_class(classes)
    for cutout_id, meta in cutout_index.items():
        _, depth = parse_cutout_id(cutout_id)
        per_depth_sizes[depth].append(meta["size"])

    result: dict[str, dict[str, Any]] = {}
    for depth, sizes in per_depth_sizes.items():
        n = len(sizes)
        if n == 0:
            result[depth] = {
                "n_cutouts": 0,
                "n_singletons": 0,
                "singleton_ratio": None,
                "mean_class_size": None,
                "median_class_size": None,
                "survival_count": 0,
                "survival_ratio": None,
            }
            continue
        n_singletons = sum(1 for s in sizes if s == 1)
        survival = sum(1 for s in sizes if s >= 2)
        result[depth] = {
            "n_cutouts": n,
            "n_singletons": n_singletons,
            "singleton_ratio": n_singletons / n,
            "mean_class_size": statistics.fmean(sizes),
            "median_class_size": statistics.median(sizes),
            "survival_count": survival,
            "survival_ratio": survival / n,
        }
    return result


def run_for_tau(tau: str, pc: PathConfig) -> dict[str, Any]:
    """1 つの τ について全 (α, M, σ) を集計する.

    Args:
        tau: ``"0.5" / "0.7" / "0.9"``.
        pc: PathConfig インスタンス.

    Returns:
        ``{"tau": tau, "cells": {f"A{α}_{M}": {depth: stats}}}``.
    """
    root = tau_dir(pc.outputs, tau)
    cells: dict[str, dict[str, Any]] = {}
    for level in ABST_LEVELS:
        for method in METHODS:
            path = classes_path(root, level, method)
            classes = load_classes(path)
            cells[f"A{level}_{method}"] = aggregate_one(classes)
    return {"tau": tau, "cells": cells}


def write_outputs(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    """JSON と CSV を書き出す.

    CSV は long-form: ``tau, level, method, depth, <metric...>``.

    Args:
        result: ``run_for_tau`` の出力.
        out_dir: 出力ディレクトリ.

    Returns:
        ``(json_path, csv_path)``.
    """
    tau = result["tau"]
    json_path = out_dir / f"alpha_sigma_grid_tau{tau}.json"
    csv_path = out_dir / f"alpha_sigma_grid_tau{tau}.csv"
    write_json(json_path, result)

    header = (
        "tau",
        "level",
        "method",
        "depth",
        "n_cutouts",
        "n_singletons",
        "singleton_ratio",
        "mean_class_size",
        "median_class_size",
        "survival_count",
        "survival_ratio",
    )
    rows: list[list[Any]] = []
    for level in ABST_LEVELS:
        for method in METHODS:
            cell = result["cells"][f"A{level}_{method}"]
            for depth in DEPTHS:
                s = cell[depth]
                rows.append(
                    [
                        tau,
                        level,
                        method,
                        depth,
                        s["n_cutouts"],
                        s["n_singletons"],
                        s["singleton_ratio"],
                        s["mean_class_size"],
                        s["median_class_size"],
                        s["survival_count"],
                        s["survival_ratio"],
                    ]
                )
    write_csv(csv_path, header, rows)
    return json_path, csv_path


def parse_args() -> argparse.Namespace:
    """CLI 引数."""
    parser = argparse.ArgumentParser(description="α × σ クロス表生成 (RQ2)")
    parser.add_argument(
        "--tau",
        choices=TAU_VALUES,
        default="0.7",
        help="対象とする Jaccard 閾値 (既定: 0.7)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="全 τ ({0.5, 0.7, 0.9}) を一括処理する",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="出力先ディレクトリ (省略時は outputs/scam/RQ2/)",
    )
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
        json_path, csv_path = write_outputs(result, out_dir)
        print(f"[OUTPUT] {json_path}", flush=True)
        print(f"[OUTPUT] {csv_path}", flush=True)


if __name__ == "__main__":
    main()
