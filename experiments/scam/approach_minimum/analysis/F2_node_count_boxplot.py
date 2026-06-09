"""Figure 2: Boxplot of AST node count for isolated vs clustered classes.

Loads ``E4b_node_count_raw.pkl`` and renders a 2x2 grid of boxplots
covering all 16 cells (τ × α × σ). Each subplot fixes (τ, α) and shows
σ_1 through σ_4 on the x-axis with side-by-side boxes for isolated and
clustered clusters. The member count is annotated above each box.

Output: ``thesis/SCAM2026_NoguchiH_ja/figures/exp_isolated_nodes.pdf``
"""

from __future__ import annotations

import pickle

import matplotlib.pyplot as plt
import numpy as np
from _common import OUT_DIR, ROOT

DEPTH_ORDER = ("Diff", "Brother", "ExParent", "Parent")
SIGMA_LABEL = {
    "Diff": r"$\sigma_1$",
    "Brother": r"$\sigma_2$",
    "ExParent": r"$\sigma_3$",
    "Parent": r"$\sigma_4$",
}

# Y-axis upper bound; outliers above are clipped (matched with showfliers=False)
Y_MAX = 110


def load_raw() -> dict:
    path = OUT_DIR / "E4b_node_count_raw.pkl"
    with path.open("rb") as f:
        return pickle.load(f)


def draw_panel(ax, raw: dict, tau: float, level: int) -> None:
    """Draw one (tau, level) panel with σ on x-axis and iso/clu boxes side by side."""
    iso_data = [raw[(tau, level, d, "iso")] for d in DEPTH_ORDER]
    clu_data = [raw[(tau, level, d, "clu")] for d in DEPTH_ORDER]
    iso_n = [len(v) for v in iso_data]
    clu_n = [len(v) for v in clu_data]

    positions_iso = np.arange(len(DEPTH_ORDER)) * 2.5 - 0.45
    positions_clu = np.arange(len(DEPTH_ORDER)) * 2.5 + 0.45

    box_iso = ax.boxplot(
        iso_data,
        positions=positions_iso,
        widths=0.7,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "black", "linewidth": 1.2},
    )
    box_clu = ax.boxplot(
        clu_data,
        positions=positions_clu,
        widths=0.7,
        patch_artist=True,
        showfliers=False,
        medianprops={"color": "black", "linewidth": 1.2},
    )

    for patch in box_iso["boxes"]:
        patch.set_facecolor("#f4a261")
        patch.set_edgecolor("black")
    for patch in box_clu["boxes"]:
        patch.set_facecolor("#2a9d8f")
        patch.set_edgecolor("black")

    for x, n in zip(positions_iso, iso_n):
        ax.annotate(
            f"n={n:,}",
            xy=(x, Y_MAX * 0.97),
            ha="center",
            va="top",
            fontsize=6.5,
        )
    for x, n in zip(positions_clu, clu_n):
        ax.annotate(
            f"n={n:,}",
            xy=(x, Y_MAX * 0.90),
            ha="center",
            va="top",
            fontsize=6.5,
        )

    ax.set_xticks(np.arange(len(DEPTH_ORDER)) * 2.5)
    ax.set_xticklabels([SIGMA_LABEL[d] for d in DEPTH_ORDER])
    ax.set_ylim(0, Y_MAX)
    ax.set_title(rf"$\tau={tau}$, $\alpha_{level}$", fontsize=10)
    ax.grid(True, axis="y", alpha=0.3)


def main() -> None:
    raw = load_raw()
    fig_dir = ROOT / "thesis/SCAM2026_NoguchiH_ja/figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 2, figsize=(7.2, 5.4), sharey=True)
    panel_specs = [
        (axes[0][0], 0.7, 0),
        (axes[0][1], 0.7, 1),
        (axes[1][0], 0.9, 0),
        (axes[1][1], 0.9, 1),
    ]
    for ax, tau, level in panel_specs:
        draw_panel(ax, raw, tau, level)

    for ax in axes[:, 0]:
        ax.set_ylabel("AST node count")
    for ax in axes[1, :]:
        ax.set_xlabel("Scope size")

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor="#f4a261", edgecolor="black", label="Isolated"),
        plt.Rectangle((0, 0), 1, 1, facecolor="#2a9d8f", edgecolor="black", label="Clustered"),
    ]
    fig.legend(handles=legend_handles, loc="upper center", ncol=2, fontsize=9, frameon=False, bbox_to_anchor=(0.5, 1.02))

    fig.tight_layout()
    out_pdf = fig_dir / "exp_isolated_nodes.pdf"
    fig.savefig(out_pdf, bbox_inches="tight")
    print(f"Wrote {out_pdf}")


if __name__ == "__main__":
    main()
