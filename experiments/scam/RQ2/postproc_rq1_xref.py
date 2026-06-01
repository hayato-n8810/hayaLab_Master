"""RQ1 既知パターン検出結果と RQ2 集約結果の突き合わせ.

各 pattern_id (1..10) について、RQ1 で ``diff_linked=true`` と判定された
mb_id 集合 ``M_p`` を取得し、RQ2 集約結果 (τ, α, M) における各 mb_id の所属
クラスを参照して、以下を集計する。

* ``n_passes``                 — ``|M_p|`` (RQ1 の Stage~B 通過件数).
* ``n_unique_classes``         — ``M_p`` の mb_id が分散したクラス数.
                                  サイズ別 (Diff/Brother/.../Parent) と "any"
                                  (4 サイズの cutout を全て集める) で別個に
                                  集計する.
* ``top_class_share``          — 最大集中クラスが ``M_p`` を覆う比率.
* ``top_class_id``             — その class_id.
* ``size_distribution``        — Top-K クラスのサイズ分布 (デバッグ用).

Input:
    - ``outputs/scam/RQ1/matches.jsonl``
    - ``outputs/scam/approach_temp_v2_jaccard_tau{tau}/classes_A{n}_M{m}.json``
Output:
    - ``outputs/scam/RQ2/rq1_xref_tau{tau}.json``
    - ``outputs/scam/RQ2/rq1_xref_tau{tau}.csv``

実行例:
    uv run python experiments/scam/RQ2/postproc_rq1_xref.py --tau 0.7
    uv run python experiments/scam/RQ2/postproc_rq1_xref.py --tau 0.7 \\
        --levels 1 --methods M1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
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


def load_rq1_matches(matches_path: Path) -> dict[int, list[int]]:
    """``matches.jsonl`` を読み込み、``{target_id: [mb_id, ...]}`` に整理する.

    ``diff_linked=true`` の行のみを対象とする.

    Args:
        matches_path: ``outputs/scam/RQ1/matches.jsonl``.

    Returns:
        ``{target_id: sorted_unique_mb_id_list}``.

    Raises:
        FileNotFoundError: ファイル不在.
    """
    if not matches_path.exists():
        raise FileNotFoundError(f"RQ1 matches.jsonl が見つかりません: {matches_path}")
    by_target: dict[int, set[int]] = defaultdict(set)
    with matches_path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            row = json.loads(line)
            if not row.get("diff_linked"):
                continue
            by_target[int(row["target_id"])].add(int(row["mb_id"]))
    return {k: sorted(v) for k, v in by_target.items()}


def class_distribution_for_mbs(
    cutout_index: dict[str, dict[str, Any]],
    mb_ids: list[int],
    depths_subset: list[str] | None = None,
) -> dict[str, Any]:
    """指定された mb_id 集合の所属クラス分布を求める.

    Args:
        cutout_index: ``cutout_to_class`` の出力.
        mb_ids: 対象 mb_id リスト.
        depths_subset: 制限するサイズ (例: ``["Diff"]``). ``None`` の場合は
            4 サイズすべてを対象とする.

    Returns:
        ``{
            "n_passes": int,                       # mb_ids の長さ
            "n_cutouts_seen": int,                 # cutout_index で発見できた件数
            "n_unique_classes": int,
            "top_class_id": str | None,
            "top_class_share": float | None,       # top_class_count / n_cutouts_seen
            "class_size_top_k": list[(class_id, count)],  # 上位 5
        }``.
    """
    if depths_subset is None:
        depths_subset = list(DEPTHS)
    counter: Counter[str] = Counter()
    seen = 0
    for mb_id in mb_ids:
        for depth in depths_subset:
            key = f"{mb_id}_{depth}"
            meta = cutout_index.get(key)
            if meta is None:
                continue
            counter[meta["class_id"]] += 1
            seen += 1
    if seen == 0:
        return {
            "n_passes": len(mb_ids),
            "n_cutouts_seen": 0,
            "n_unique_classes": 0,
            "top_class_id": None,
            "top_class_share": None,
            "class_size_top_k": [],
        }
    top = counter.most_common(5)
    top_class_id, top_count = top[0]
    return {
        "n_passes": len(mb_ids),
        "n_cutouts_seen": seen,
        "n_unique_classes": len(counter),
        "top_class_id": top_class_id,
        "top_class_share": top_count / seen,
        "class_size_top_k": [(cid, c) for cid, c in top],
    }


def aggregate_one(
    classes: list[dict[str, Any]],
    matches: dict[int, list[int]],
) -> dict[str, Any]:
    """1 設定 (1 つの (τ, α, M)) について全 target を集計する."""
    cutout_index = cutout_to_class(classes)
    by_target: dict[int, dict[str, Any]] = {}
    for target_id, mb_ids in sorted(matches.items()):
        per_depth: dict[str, Any] = {depth: class_distribution_for_mbs(cutout_index, mb_ids, [depth]) for depth in DEPTHS}
        any_depth = class_distribution_for_mbs(cutout_index, mb_ids, list(DEPTHS))
        by_target[target_id] = {
            "n_passes": len(mb_ids),
            "any": any_depth,
            **{f"{depth}": per_depth[depth] for depth in DEPTHS},
        }
    return by_target


def run_for_tau(
    tau: str,
    pc: PathConfig,
    levels: list[int],
    methods: list[str],
    matches_path: Path,
) -> dict[str, Any]:
    """1 つの τ について指定 (α, M) 設定群を集計する."""
    matches = load_rq1_matches(matches_path)
    root = tau_dir(pc.outputs, tau)
    cells: dict[str, dict[str, Any]] = {}
    for level in levels:
        for method in methods:
            path = classes_path(root, level, method)
            classes = load_classes(path)
            cells[f"A{level}_{method}"] = aggregate_one(classes, matches)
    return {
        "tau": tau,
        "rq1_targets": sorted(matches.keys()),
        "rq1_pass_counts": {str(t): len(v) for t, v in sorted(matches.items())},
        "cells": cells,
    }


def write_outputs(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    """JSON / CSV を書き出す.

    CSV long-form: ``tau, level, method, target_id, depth_scope, n_passes,
    n_cutouts_seen, n_unique_classes, top_class_share, top_class_id``.
    """
    tau = result["tau"]
    json_path = out_dir / f"rq1_xref_tau{tau}.json"
    csv_path = out_dir / f"rq1_xref_tau{tau}.csv"
    write_json(json_path, result)

    header = (
        "tau",
        "level",
        "method",
        "target_id",
        "depth_scope",
        "n_passes",
        "n_cutouts_seen",
        "n_unique_classes",
        "top_class_share",
        "top_class_id",
    )
    rows: list[list[Any]] = []
    for cell_key, cell in result["cells"].items():
        # cell_key 例: "A1_M1"
        level_str, method = cell_key.split("_", 1)
        level = int(level_str[1:])
        for target_id, per_scope in cell.items():
            for scope in ("any", *DEPTHS):
                stat = per_scope[scope]
                rows.append(
                    [
                        tau,
                        level,
                        method,
                        target_id,
                        scope,
                        stat["n_passes"],
                        stat["n_cutouts_seen"],
                        stat["n_unique_classes"],
                        stat["top_class_share"],
                        stat["top_class_id"],
                    ]
                )
    write_csv(csv_path, header, rows)
    return json_path, csv_path


def parse_args() -> argparse.Namespace:
    """CLI 引数."""
    parser = argparse.ArgumentParser(description="RQ1 検出結果と RQ2 集約結果の突き合わせ")
    parser.add_argument("--tau", choices=TAU_VALUES, default="0.7")
    parser.add_argument("--all-tau", action="store_true")
    parser.add_argument(
        "--levels",
        nargs="*",
        type=int,
        default=list(ABST_LEVELS),
        help="集計対象の抽象化レベル (既定: 0 1 2 3)",
    )
    parser.add_argument(
        "--methods",
        nargs="*",
        choices=METHODS,
        default=list(METHODS),
        help="集計対象のメソッド (既定: M1 M2)",
    )
    parser.add_argument(
        "--matches",
        type=Path,
        default=None,
        help="RQ1 matches.jsonl のパス (省略時は outputs/scam/RQ1/matches.jsonl)",
    )
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    """エントリポイント."""
    args = parse_args()
    pc = PathConfig()
    out_dir = args.output_dir or output_dir(pc.outputs)
    out_dir.mkdir(parents=True, exist_ok=True)
    matches_path = args.matches or (pc.outputs / "scam" / "RQ1" / "matches.jsonl")

    targets: list[str] = list(TAU_VALUES) if args.all_tau else [args.tau]
    for tau in targets:
        print(f"[TAU] {tau}", flush=True)
        result = run_for_tau(tau, pc, args.levels, args.methods, matches_path)
        json_path, csv_path = write_outputs(result, out_dir)
        print(f"[OUTPUT] {json_path}", flush=True)
        print(f"[OUTPUT] {csv_path}", flush=True)


if __name__ == "__main__":
    main()
