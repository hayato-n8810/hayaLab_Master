"""Figure 1: Total class count over scope size σ for (α, τ) combinations.

Reads ``E2_grid.csv`` and plots num_classes as a function of σ (depth ordering:
Diff → Brother → ExParent → Parent) with 4 lines for the (α, τ) combinations.

Output: ``thesis/SCAM2026_NoguchiH_ja/figures/exp_aggregation.pdf``
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
from _common import OUT_DIR, ROOT

DEPTH_ORDER = ("Diff", "Brother", "ExParent", "Parent")
SIGMA_LABEL = {
    "Diff": r"$\sigma_1$",
    "Brother": r"$\sigma_2$",
    "ExParent": r"$\sigma_3$",
    "Parent": r"$\sigma_4$",
}


def load_e2_grid() -> dict[tuple[float, int, str], dict[str, float]]:
    """Load E2_grid.csv keyed by (tau, level, depth)."""
    path = OUT_DIR / "E2_grid.csv"
    rows: dict[tuple[float, int, str], dict[str, float]] = {}
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (float(row["tau"]), int(row["level"]), row["depth"])
            rows[key] = {
                "num_classes": float(row["num_classes"]),
                "isolated_ratio": float(row["isolated_ratio"]),
            }
    return rows


def main() -> None:
    grid = load_e2_grid()
    fig_dir = ROOT / "thesis/SCAM2026_NoguchiH_ja/figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    combos = [
        (0.7, 0, "o-", r"$\tau=0.7, \alpha_0$"),
        (0.7, 1, "s-", r"$\tau=0.7, \alpha_1$"),
        (0.9, 0, "o--", r"$\tau=0.9, \alpha_0$"),
        (0.9, 1, "s--", r"$\tau=0.9, \alpha_1$"),
    ]

    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    x = list(range(len(DEPTH_ORDER)))
    xlabels = [SIGMA_LABEL[d] for d in DEPTH_ORDER]

    for tau, level, style, label in combos:
        y = [grid[(tau, level, d)]["num_classes"] for d in DEPTH_ORDER]
        ax.plot(x, y, style, label=label, markersize=5)

    ax.set_xticks(x)
    ax.set_xticklabels(xlabels)
    ax.set_xlabel("Scope size")
    ax.set_ylabel("Total class count")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8, framealpha=0.9)
    fig.tight_layout()

    out_pdf = fig_dir / "exp_aggregation.pdf"
    fig.savefig(out_pdf)
    print(f"Wrote {out_pdf}")


if __name__ == "__main__":
    main()
