"""コサイン類似度平均の箱ひげ図を作成する。"""

import re
from pathlib import Path
from typing import Iterable, Optional, Set

import matplotlib.pyplot as plt

import hayalab
from hayalab.config import PathConfig

# recall_precision.py と同じ feature_id の対応
FEATURE_INFO = [
    (1, "ID 1"),
    (5, "ID 2"),
    (14, "ID 3"),
    (84, "ID 4"),
    (92, "ID 5"),
    (139, "ID 6"),
]


def load_origin_ids(json_path: Path, feature_id: int) -> Set[int]:
    """slow_pattern.json から feature_id に対応する origin ID 集合を取得する。"""
    data = hayalab.read_json(str(json_path))
    for item in data:
        if item.get("feature_id") == feature_id:
            return set(item.get("ids", []))
    return set()


def extract_slow_id(name: str) -> Optional[int]:
    """対象名から slow ID を抽出する。例: block_slow_12345, slow_123.js"""
    patterns = [
        r"(?:^|_)slow_(\d+)$",  # block_slow_12345
        r"(?:^|/)slow_(\d+)\.js$",  # .../slow_123.js
        r"slow_(\d+)",  # フォールバック
    ]
    for pattern in patterns:
        match = re.search(pattern, name)
        if match:
            return int(match.group(1))
    return None


def load_means(similarity_json_path: Path) -> list[tuple[Optional[int], float]]:
    """similarity JSON から (抽出ID, mean) の配列を返す。"""
    data = hayalab.read_json(str(similarity_json_path))
    rows: list[tuple[Optional[int], float]] = []
    for item in data.get("results", []):
        mean_value = float(item.get("mean", 0.0))
        file_name = str(item.get("file", ""))
        rows.append((extract_slow_id(file_name), mean_value))
    return rows


def split_means_by_origin(rows: Iterable[tuple[Optional[int], float]], origin_ids: Set[int]) -> tuple[list[float], list[float]]:
    """origin ID に含まれるデータとそれ以外に分割する。"""
    non_pattern: list[float] = []
    pattern: list[float] = []

    for slow_id, mean_value in rows:
        if slow_id is not None and slow_id in origin_ids:
            pattern.append(mean_value)
        else:
            non_pattern.append(mean_value)

    return non_pattern, pattern


def plot_microbenchmark_pattern_vs_other(
    all_data: list[tuple[str, list[float], list[float]]],
    output_path: Path,
) -> None:
    """各 ID ごとに non-pattern / pattern を横並びで描画する。"""
    plt.figure(figsize=(18, 8))
    plt.rcParams["font.size"] = 13

    box_data: list[list[float]] = []
    positions: list[float] = []
    group_centers: list[float] = []

    box_width = 0.8
    group_gap = 2.5
    pos = 1.0

    for label, non_pattern, pattern in all_data:
        box_data.extend([non_pattern, pattern])
        positions.extend([pos, pos + box_width])
        group_centers.append(pos + box_width / 2)
        pos += group_gap

    bp = plt.boxplot(
        box_data,
        positions=positions,
        widths=box_width,
        patch_artist=True,
        showmeans=True,
        meanprops={"marker": "o", "markerfacecolor": "black", "markeredgecolor": "black", "markersize": 8},
    )

    # 箱の色を設定（非pattern: 白、pattern: 赤）
    for i, box in enumerate(bp["boxes"]):
        if i % 2 == 0:  # 非pattern
            box.set_facecolor("white")
            box.set_edgecolor("black")
        else:  # pattern
            box.set_facecolor("red")
            box.set_edgecolor("darkred")
            box.set_alpha(0.7)

    plt.xticks(group_centers, [item[0] for item in all_data])
    plt.tick_params(axis="x", pad=10)
    plt.ylabel("Cosine Similarity Mean")
    plt.ylim(-0.05, 1.05)
    plt.grid(True, axis="y", alpha=0.3, linestyle="--")

    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    legends = [
        Patch(facecolor="white", edgecolor="black", label="Non-pattern"),
        Patch(facecolor="red", edgecolor="darkred", alpha=0.7, label="Pattern"),
        Line2D([0], [0], marker="o", color="w", label="Mean", markerfacecolor="black", markersize=8),
    ]
    plt.legend(handles=legends, fontsize=12, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, frameon=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved: {output_path}")


def plot_github_all_ids(
    all_data: list[tuple[str, list[float]]],
    output_path: Path,
) -> None:
    """GitHub の各 ID の mean 分布を 1 箱ずつ並べて描画する。"""
    plt.figure(figsize=(16, 8))
    plt.rcParams["font.size"] = 13

    labels = [f"{name}\n(n={len(values)})" for name, values in all_data]
    values = [item[1] for item in all_data]

    plt.boxplot(
        values,
        labels=labels,
        patch_artist=True,
        showmeans=True,
        meanprops={"marker": "o", "markerfacecolor": "black", "markeredgecolor": "black", "markersize": 8},
        boxprops={"facecolor": "white", "color": "black"},
        whiskerprops={"color": "black"},
        capprops={"color": "black"},
        medianprops={"color": "orange"},
    )

    plt.ylabel("Cosine Similarity Mean")
    plt.grid(True, axis="y", alpha=0.3, linestyle="--")
    plt.ylim(-1.0, 1.0)

    from matplotlib.lines import Line2D

    legends = [
        Line2D([0], [0], marker="o", color="w", label="Mean", markerfacecolor="black", markersize=8),
    ]
    plt.legend(handles=legends, loc="upper center", bbox_to_anchor=(0.5, -0.1), frameon=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    config = PathConfig()

    pattern_json = f"{config.outputs}/pattern/slow_pattern.json"  # パターンの元となった実装対のIDが記載されたJSONファイルのパス
    similarity_root = f"{config.outputs}/ql_analysis/"

    mb_plot_data: list[tuple[str, list[float], list[float]]] = []
    github_plot_data: list[tuple[str, list[float]]] = []

    for index, (feature_id, label) in enumerate(FEATURE_INFO, start=1):
        origin_ids = load_origin_ids(pattern_json, feature_id)

        mb_similarity_path = similarity_root / "microbenchmark" / "cosine_sim" / f"cosine_sim_id_{index}.json"
        mb_rows = load_means(mb_similarity_path)
        non_pattern_means, pattern_means = split_means_by_origin(mb_rows, origin_ids)
        mb_plot_data.append((label, non_pattern_means, pattern_means))

        github_similarity_path = similarity_root / "github" / "bachelor" / f"id_{index}" / f"id_{index}_similarity.json"
        github_rows = load_means(github_similarity_path)
        github_means = [mean_value for _, mean_value in github_rows]
        github_plot_data.append((label, github_means))

        print(f"{label}: MB non-pattern={len(non_pattern_means)}, MB pattern={len(pattern_means)}, GitHub={len(github_means)}")

    plot_microbenchmark_pattern_vs_other(
        mb_plot_data,
        config.outputs / "ql_analysis" / "microbenchmark" / "boxplot_microbenchmark_pattern_vs_other.png",
    )
    plot_github_all_ids(
        github_plot_data,
        config.outputs / "ql_analysis" / "github" / "boxplot_all_ids.png",
    )
