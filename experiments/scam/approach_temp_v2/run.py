r"""approach_temp_v2 のメイン実行スクリプト.

`docs/aggregate.md` の M0/M1/M2/M3 を ``outputs/scam/approach/03_abstract/``
の出力に対して走らせ、approach_temp の M3/M4/M5 と比較可能な形式で
クラスタ結果と軌跡を出力する．

CLI usage::

    uv run python experiments/scam/approach_temp_v2/run.py \
        --input-dir outputs/scam/approach/03_abstract \
        --output outputs/scam/approach_temp_v2 \
        --levels 0 1 2 3 \
        --methods M0 M1 M2 M3 \
        --m1-mode exact \
        --m2-mode exact --m2-n 2

approach_temp との比較を直接比較したい場合は ``--m3-tau-sim 0.5
--m3-kappa 3.0 --m3-rho 0.5`` をデフォルトのまま使う（approach_temp と
同じ集約挙動）．

Outputs (under ``--output``):

    filtered_out.json
    classes_A{level}_{method}.json  (per level x method)
    trajectory_{method}.json        (per method)
    summary.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from ast_node import Pattern  # noqa: E402
from loader import filter_empty_patterns, load_patterns_for_level  # noqa: E402
from observe import (  # noqa: E402
    LEVELS as ALL_LEVELS,
)
from observe import (
    _dispatch_cluster,
    build_trajectory,
    check_monotonicity,
    save_classes,
    save_trajectory,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Compare aggregate.md M0/M1/M2/M3 on 03_abstract output",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--input-dir",
        default="outputs/scam/approach/03_abstract",
        help="Directory containing 03_abstract_level{0,1,2,3}.json",
    )
    p.add_argument(
        "--output",
        default="outputs/scam/approach_temp_v2",
        help="Output directory",
    )
    p.add_argument(
        "--levels",
        nargs="+",
        type=int,
        default=[0, 1, 2, 3],
        help="Abstraction levels to load",
    )
    p.add_argument(
        "--methods",
        nargs="+",
        default=["M0", "M1", "M2", "M3"],
        choices=["M0", "M1", "M2", "M3"],
        help="Clustering methods to run",
    )
    p.add_argument(
        "--min-nodes",
        type=int,
        default=2,
        help="Minimum nodes per pattern (smaller patterns are filtered)",
    )
    p.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Limit to first N microbenchmarks (matches approach_temp's --sample). The same mb_id subset is applied across all abstraction levels.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel worker processes for exact-mode key computation (M0 / M1 exact / M2 exact).  Output is unchanged regardless of value.  Jaccard modes and M3 LGG remain sequential.",
    )
    # M1 parameters
    p.add_argument("--m1-mode", choices=["exact", "jaccard"], default="exact")
    p.add_argument(
        "--m1-tau-jaccard",
        type=float,
        default=0.7,
        help="M1 jaccard threshold (SourcererCC, ICSE 2016 で標準 0.7. 感度分析として 0.5 / 0.9 も検討)",
    )
    # 旧 --m1-include-parent-name オプションは廃止 (token は (name, value) 固定).
    # M2 parameters
    p.add_argument("--m2-mode", choices=["exact", "jaccard"], default="exact")
    p.add_argument("--m2-n", type=int, default=2, help="n for M2 n-gram")
    p.add_argument(
        "--m2-tau-jaccard",
        type=float,
        default=0.7,
        help="M2 jaccard threshold (SourcererCC 標準 0.7)",
    )
    # M3 parameters (mirror approach_temp defaults for direct comparison)
    p.add_argument(
        "--m3-tau-sim",
        type=float,
        default=0.5,
        help="M3 LGG similarity threshold (LASE, ICSE 2013 系の経験値 0.5)",
    )
    p.add_argument("--m3-kappa", type=float, default=3.0)
    p.add_argument("--m3-rho", type=float, default=0.5)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Load patterns at every requested level
    # ------------------------------------------------------------------
    # When --sample is given, lock the mb_id subset from the first level so
    # every level loads the same mb_ids (otherwise file-order truncation could
    # diverge across files).
    patterns_by_level: dict[int, list[Pattern]] = {}
    excluded_all: list[dict] = []
    sample_mb_ids: set[int] | None = None
    for L in args.levels:
        path = input_dir / f"03_abstract_level{L}.json"
        if not path.exists():
            logger.warning("Missing input %s", path)
            continue
        if sample_mb_ids is None and args.sample:
            # First level: take first N records in file order
            patterns = load_patterns_for_level(path, L, sample_n=args.sample)
            sample_mb_ids = {p.mb_id for p in patterns}
            logger.info(
                "  pinned sample_mb_ids: %d mb_ids from L%d",
                len(sample_mb_ids),
                L,
            )
        else:
            patterns = load_patterns_for_level(path, L, sample_mb_ids=sample_mb_ids)
        kept, excluded = filter_empty_patterns(patterns, min_nodes=args.min_nodes)
        patterns_by_level[L] = kept
        # exclusions are level-independent in practice; record from L0 first time
        if not excluded_all and L == args.levels[0]:
            excluded_all = excluded

    if not patterns_by_level:
        logger.error("No patterns loaded; aborting.")
        return 1

    # Save filtered_out
    with (output_dir / "filtered_out.json").open("w", encoding="utf-8") as f:
        json.dump(excluded_all, f, indent=2, ensure_ascii=False)
    logger.info("Wrote filtered_out.json (%d records)", len(excluded_all))

    # Build mb_depth_lookup from L0 (or first available level)
    first_L = min(patterns_by_level.keys())
    mb_depth_lookup = {p.cutout_id: (p.mb_id, p.depth) for p in patterns_by_level[first_L]}
    cutout_ids_universal = sorted(mb_depth_lookup.keys())

    # ------------------------------------------------------------------
    # 2. Build params dict for dispatch
    # ------------------------------------------------------------------
    params = {
        "workers": args.workers,
        "m1_mode": args.m1_mode,
        "m1_tau_jaccard": args.m1_tau_jaccard,
        "m2_mode": args.m2_mode,
        "m2_n": args.m2_n,
        "m2_tau_jaccard": args.m2_tau_jaccard,
        "m3_tau_sim": args.m3_tau_sim,
        "m3_kappa": args.m3_kappa,
        "m3_rho": args.m3_rho,
    }

    # ------------------------------------------------------------------
    # 3. Run each (method, level) cell
    # ------------------------------------------------------------------
    t_start = time.time()
    summary = {
        "input_dir": str(input_dir),
        "output": str(output_dir),
        "levels": list(args.levels),
        "methods": list(args.methods),
        "params": params,
        "sample_size_requested": args.sample,
        "sample_n_mb_ids": len(sample_mb_ids) if sample_mb_ids else None,
        "n_patterns_per_level": {L: len(ps) for L, ps in patterns_by_level.items()},
        "n_excluded_total": len(excluded_all),
        "class_counts": {},
        "monotonicity_violations": {},
    }

    for method in args.methods:
        logger.info("=== Method %s ===", method)
        classes_by_level: dict[int, dict[str, list[str]]] = {}
        for L, patterns in patterns_by_level.items():
            logger.info("  L%d: %d patterns", L, len(patterns))
            classes = _dispatch_cluster(method, patterns, params)
            classes_by_level[L] = classes
            save_classes(classes, method, L, patterns, output_dir)
            sizes = sorted({len(m) for m in classes.values()})
            summary["class_counts"][f"A{L}_{method}"] = {
                "n_classes": len(classes),
                "sizes": sizes,
            }

        # Trajectory across levels
        traj = build_trajectory(classes_by_level, cutout_ids_universal, mb_depth_lookup)
        save_trajectory(traj, method, output_dir)

        # Monotonicity (M0/M1/M2 are deterministic so this should be 0 unless
        # abstraction levels actually re-split groups, which is impossible by
        # design — but we record it for parity with approach_temp).
        viol = check_monotonicity(classes_by_level)
        summary["monotonicity_violations"][method] = viol
        logger.info("  monotonicity violations: %d", viol)

    summary["elapsed_seconds"] = round(time.time() - t_start, 2)
    with (output_dir / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info("Done in %.1fs → %s", summary["elapsed_seconds"], output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
