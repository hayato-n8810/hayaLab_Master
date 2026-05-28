r"""Main runner for Slow Pattern Clustering pipeline.

CLI usage:
    uv run python experiments/scam/approach_temp/run.py \
        --input outputs/scam/approach/01_cutouts.json \
        --output outputs/scam/approach_temp/ \
        --levels 0 1 2 3 4 5 \
        --methods M0 M1 M2 M3 \
        --sample 100

Execution order:
    load -> filter -> abstract (all levels) -> cluster (all methods)
    -> observe -> export -> visualize -> summary

Outputs (all under --output directory):
    filtered_out.json
    trajectory_{method}.json  (per method)
    classes_A{level}_{method}.json  (per level x method)
    sankey_{method}.html  (per method)
    summary.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup sys.path so sibling modules are importable
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from abstract import abstract_cutout  # noqa: E402
from export import export_classes  # noqa: E402
from loader import filter_cutouts, load_cutouts, save_filtered_out  # noqa: E402
from observe import (  # noqa: E402
    AllResults,
    build_trajectory,
    check_monotonicity,
    run_all,
    save_trajectory,
)
from visualize_sankey import load_trajectory, render_sankey  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Slow Pattern Clustering pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        default="outputs/scam/approach/01_cutouts.json",
        help="Path to 01_cutouts.json",
    )
    parser.add_argument(
        "--output",
        default="outputs/scam/approach_temp",
        help="Output directory",
    )
    parser.add_argument(
        "--levels",
        nargs="+",
        type=int,
        default=list(range(6)),
        help="Abstraction levels to run (0-5)",
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["M0", "M1", "M2", "M3"],
        help="Clustering methods to run (M0 M1 M2 M3)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Limit to first N microbenchmarks (for quick testing)",
    )
    parser.add_argument(
        "--no-visualize",
        action="store_true",
        help="Skip Sankey HTML generation",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Skip classes JSON export",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Number of parallel worker processes for clustering. "
            "1 = sequential (default). "
            "Use os.cpu_count() or a specific number (e.g. 4). "
            "Each worker handles one (level, method) task independently."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Run the full pipeline."""
    args = parse_args()
    t_start = time.perf_counter()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    levels: list[int] = sorted(set(args.levels))
    methods: list[str] = list(dict.fromkeys(args.methods))  # preserve order, deduplicate

    logger.info("=== Slow Pattern Clustering Pipeline ===")
    logger.info("Input:   %s", input_path)
    logger.info("Output:  %s", output_dir)
    logger.info("Levels:  %s", levels)
    logger.info("Methods: %s", methods)
    if args.sample:
        logger.info("Sample:  first %d microbenchmarks", args.sample)
    if args.workers > 1:
        logger.info("Workers: %d parallel processes", args.workers)

    # ------------------------------------------------------------------
    # Step 1: Load
    # ------------------------------------------------------------------
    logger.info("[1/7] Loading cutouts ...")
    all_cutouts = load_cutouts(input_path)

    if args.sample:
        # Limit by unique mb_id (not total cutout count)
        mb_ids = list(dict.fromkeys(c.mb_id for c in all_cutouts))
        sampled_ids = set(mb_ids[: args.sample])
        all_cutouts = [c for c in all_cutouts if c.mb_id in sampled_ids]
        logger.info("Sampled %d cutouts from %d mb_ids", len(all_cutouts), len(sampled_ids))

    # ------------------------------------------------------------------
    # Step 2: Filter
    # ------------------------------------------------------------------
    logger.info("[2/7] Filtering content-free cutouts ...")
    valid_cutouts, excluded_cutouts = filter_cutouts(all_cutouts)
    save_filtered_out(excluded_cutouts, output_dir)

    logger.info("Valid: %d, Excluded: %d", len(valid_cutouts), len(excluded_cutouts))

    if not valid_cutouts:
        logger.error("No valid cutouts after filtering. Aborting.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 3: Abstract (all levels) — pre-compute for export
    # ------------------------------------------------------------------
    logger.info("[3/7] Abstracting cutouts at all levels ...")
    patterns_by_level: dict[int, dict[str, object]] = {}
    for level in levels:
        patterns = [abstract_cutout(c, level) for c in valid_cutouts]
        patterns_by_level[level] = {p.cutout_id: p for p in patterns}

    # ------------------------------------------------------------------
    # Step 4: Cluster (all methods)
    # ------------------------------------------------------------------
    logger.info("[4/7] Running clustering ...")
    all_results: AllResults = run_all(valid_cutouts, levels=levels, methods=methods, workers=args.workers)

    # ------------------------------------------------------------------
    # Step 5: Observe — trajectories + monotonicity
    # ------------------------------------------------------------------
    logger.info("[5/7] Building trajectories ...")
    trajectories_by_method: dict[str, list] = {}
    for method in methods:
        traj = build_trajectory(all_results, method, levels=levels)
        trajectories_by_method[method] = traj
        save_trajectory(traj, method, output_dir)

    # Monotonicity check (M0 should always pass; others may have violations)
    logger.info("Checking monotonicity ...")
    monotonicity_violations: dict[str, int] = {}
    for method in methods:
        violations = check_monotonicity(all_results, method, levels=levels)
        monotonicity_violations[method] = violations
        if violations > 0:
            if method == "M0":
                logger.warning(
                    "WARN: Method %s has %d monotonicity violations (implementation bug!).",
                    method,
                    violations,
                )
            else:
                logger.info(
                    "Method %s: %d class re-assignments across levels (expected per §5.1).",
                    method,
                    violations,
                )

    # ------------------------------------------------------------------
    # Step 6: Export classes
    # ------------------------------------------------------------------
    if not args.no_export:
        logger.info("[6/7] Exporting class files ...")
        export_classes(
            all_results,
            valid_cutouts,
            patterns_by_level,
            output_dir,
            levels=levels,
            methods=methods,
        )
    else:
        logger.info("[6/7] Skipping export (--no-export).")

    # ------------------------------------------------------------------
    # Step 7: Visualize Sankey
    # ------------------------------------------------------------------
    if not args.no_visualize:
        logger.info("[7/7] Generating Sankey diagrams ...")
        for method in methods:
            traj_path = output_dir / f"trajectory_{method}.json"
            if traj_path.exists():
                traj_data = load_trajectory(traj_path)
                sankey_path = output_dir / f"sankey_{method}.html"
                try:
                    render_sankey(method, traj_data, sankey_path, levels=levels)
                except ImportError:
                    logger.warning(
                        "plotly not available; skipping Sankey for %s. Run: uv add plotly",
                        method,
                    )
    else:
        logger.info("[7/7] Skipping visualization (--no-visualize).")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    t_end = time.perf_counter()
    elapsed = t_end - t_start

    summary: dict = {
        "input": str(input_path),
        "output": str(output_dir),
        "levels": levels,
        "methods": methods,
        "workers": args.workers,
        "n_cutouts_total": len(all_cutouts),
        "n_cutouts_valid": len(valid_cutouts),
        "n_cutouts_excluded": len(excluded_cutouts),
        "elapsed_seconds": round(elapsed, 2),
        "monotonicity_violations": monotonicity_violations,
        "class_counts": {},
    }

    for level in levels:
        for method in methods:
            classes = all_results.get(level, {}).get(method, {})
            key = f"A{level}_{method}"
            summary["class_counts"][key] = {
                "n_classes": len(classes),
                "sizes": sorted({len(m) for m in classes.values()}),
            }

    summary_path = output_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info("Summary written to %s", summary_path)

    logger.info("=== Pipeline complete in %.2f seconds ===", elapsed)

    # Print quick summary
    print("\n--- Summary ---")
    print(f"Valid cutouts: {len(valid_cutouts)} (excluded: {len(excluded_cutouts)})")
    for method in methods:
        violations = monotonicity_violations.get(method, 0)
        print(f"  {method}: monotonicity violations = {violations}")
        for level in levels:
            classes = all_results.get(level, {}).get(method, {})
            print(f"    A{level}: {len(classes)} classes")


if __name__ == "__main__":
    main()
