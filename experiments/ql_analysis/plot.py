"""
コサイン類似度の可視化
ヒストグラム + マーカーで全体の分布とpatternIDの位置を表現する
"""

import matplotlib.pyplot as plt
import numpy as np

import hayalab
from hayalab.config import PathConfig


def load_pattern_ids(json_path: str, feature_id: int) -> set[int]:
    """
    JSONファイルから指定したfeature_idのidsをpatternIDとして読み込む

    Args:
        json_path: JSONファイルのパス
        feature_id: 対象のfeature_id

    Returns:
        patternIDのセット
    """
    data = hayalab.read_json(json_path)

    for item in data:
        if item.get("feature_id") == feature_id:
            return set(item.get("ids", []))

    return set()


def extract_id_from_filename(filename: str) -> int | None:
    """
    ファイル名からIDを抽出する

    Args:
        filename: ファイル名（例: "slow_1008"）

    Returns:
        ID（整数）またはNone
    """
    if filename.startswith("slow_"):
        try:
            return int(filename.replace("slow_", ""))
        except ValueError:
            return None
    return None


def load_data_for_feature(
    cosine_sim_path: str,
    pattern_ids: set[int],
) -> tuple[list[float], list[float]]:
    """
    特定のfeatureのデータを読み込む

    Args:
        cosine_sim_path: コサイン類似度JSONファイルのパス
        pattern_ids: patternIDのセット

    Returns:
        (non_pattern_means, pattern_means)のタプル
    """
    data = hayalab.read_json(cosine_sim_path)
    results = data.get("results", [])

    non_pattern_means = []
    pattern_means = []

    for result in results:
        mean_value = result.get("mean", 0.0)

        # ファイル名からIDを抽出
        filename = result.get("file", "")
        file_id = extract_id_from_filename(filename)

        # patternIDに含まれるかどうかで分類
        if file_id and file_id in pattern_ids:
            pattern_means.append(mean_value)
        else:
            non_pattern_means.append(mean_value)

    return non_pattern_means, pattern_means


def plot_strip_plot_all_features(
    all_data: list[tuple[str, list[float], list[float]]],
    output_path: str,
):
    """
    全てのfeatureのストリッププロットを横並びで表示

    Args:
        all_data: [(feature_name, non_pattern_means, pattern_means), ...]のリスト
        output_path: 出力画像パス
    """
    plt.figure(figsize=(16, 8))
    plt.rcParams["font.size"] = 20

    x_positions = []
    feature_names = []

    for i, (feature_name, non_pattern_means, pattern_means) in enumerate(all_data):
        x_pos = i + 1
        x_positions.append(x_pos)
        feature_names.append(feature_name)

        # ジッター（横方向の微小なランダムずらし）を追加
        jitter_strength = 0.15

        # 非patternIDの点（白/グレー）
        if non_pattern_means:
            x_jitter = np.random.normal(x_pos, jitter_strength, len(non_pattern_means))
            plt.scatter(
                x_jitter,
                non_pattern_means,
                color="white",
                s=50,
                alpha=1,
                edgecolors="black",
                linewidths=0.5,
                zorder=2,
            )

        # patternIDの点（赤）
        if pattern_means:
            x_jitter = np.random.normal(x_pos, jitter_strength, len(pattern_means))
            plt.scatter(
                x_jitter,
                pattern_means,
                color="red",
                s=50,
                alpha=1,
                edgecolors="darkred",
                linewidths=0.8,
                zorder=3,
            )

    # グラフの装飾
    plt.xlabel("Feature Type", fontsize=14, fontweight="bold", labelpad=80)
    plt.ylabel("Cosine Similarity Mean", fontsize=14, fontweight="bold", labelpad=15)

    plt.xticks(x_positions, feature_names, rotation=45, ha="right")
    plt.grid(True, axis="y", alpha=0.3, linestyle="--")

    # 凡例
    plt.scatter([], [], color="white", s=150, edgecolors="black", label="Non-pattern vectors")
    plt.scatter([], [], color="red", s=150, edgecolors="darkred", label="Pattern ID vectors")
    plt.legend(fontsize=22, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=2)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved: {output_path}")


def plot_box_plot_all_features(
    all_data: list[tuple[str, list[float], list[float]]],
    output_path: str,
):
    """

    Args:
        all_data: [(feature_name, non_pattern_means, pattern_means), ...]のリスト
        output_path: 出力画像パス
    """
    plt.figure(figsize=(16, 8))
    plt.rcParams["font.size"] = 20

    # 各featureごとに2つの箱ひげ図を作成
    all_box_data = []
    tick_positions = []
    tick_labels = []

    box_width = 0.8
    group_spacing = 2.5  # featureグループ間の間隔

    current_pos = 1
    for i, (feature_name, non_pattern_means, pattern_means) in enumerate(all_data):
        # 非patternのデータ
        all_box_data.append(non_pattern_means)
        tick_positions.append(current_pos)

        # patternのデータ（非patternの隣に接して配置）
        all_box_data.append(pattern_means)
        tick_positions.append(current_pos + box_width)

        # 次のfeatureグループの開始位置
        current_pos += group_spacing

        # feature名は2つの箱の中間に配置
        tick_labels.append("")
        tick_labels.append("")

    # 箱ひげ図を描画
    bp = plt.boxplot(
        all_box_data,
        positions=tick_positions,
        widths=box_width,
        patch_artist=True,
        showmeans=True,
        meanprops=dict(marker="o", markerfacecolor="black", markeredgecolor="black", markersize=8),
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

    # x軸のラベルを設定（各featureグループの中央）
    feature_label_positions = []
    for i in range(len(all_data)):
        base_pos = 1 + i * group_spacing
        feature_label_positions.append(base_pos + box_width / 2)

    feature_names = [name for name, _, _ in all_data]
    plt.xticks(feature_label_positions, feature_names, rotation=0, ha="center")

    # x軸のラベル（ID 1, ID 2...）をグラフから離す
    plt.tick_params(axis="x", pad=15)

    # グラフの装飾
    plt.xlabel("Feature Type", fontsize=14, fontweight="bold", labelpad=20)
    plt.ylabel("Cosine Similarity Mean", fontsize=14, fontweight="bold", labelpad=15)
    plt.grid(True, axis="y", alpha=0.3, linestyle="--")

    # y軸の範囲を設定 (0.0 から 1.0)
    plt.ylim(-0.05, 1.05)

    # 凡例
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    legend_elements = [
        Patch(facecolor="white", edgecolor="black", label="Non-pattern"),
        Patch(facecolor="red", edgecolor="darkred", alpha=0.7, label="Pattern"),
        Line2D([0], [0], marker="o", color="w", label="Mean", markerfacecolor="black", markersize=8),
    ]
    plt.legend(handles=legend_elements, fontsize=22, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved: {output_path}")


def strip_plot(
    all_data: list[float],
    output_path: str,
    label: str = "Data",
):
    """
    一つのfloatの数列を受け取ってストリッププロットを作成

    Args:
        all_data: コサイン類似度の平均値のリスト
        output_path: 出力画像パス
        label: x軸のラベル
    """
    plt.figure(figsize=(8, 8))
    plt.rcParams["font.size"] = 20

    # 単一のグループとして表示
    x_pos = 1
    jitter_strength = 0.15

    # ジッター（横方向の微小なランダムずらし）を追加
    x_jitter = np.random.normal(x_pos, jitter_strength, len(all_data))
    plt.scatter(
        x_jitter,
        all_data,
        color="white",
        s=50,
        alpha=1,
        edgecolors="black",
        linewidths=0.5,
        zorder=2,
    )

    # グラフの装飾
    plt.ylabel("Cosine Similarity Mean", fontsize=14, fontweight="bold", labelpad=15)

    plt.xticks([x_pos], [label])
    plt.xlim(0.5, 1.5)
    plt.grid(True, axis="y", alpha=0.3, linestyle="--")

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved: {output_path}")


def boxplot(data: list[list[int]], labels_name: list[str]):
    """箱ひげ図を描画する

    Args:
        data (list[list[int]]): 一つの箱ひげ図に載せるデータ
        labels_name (list[str]): 各データのラベル
    """
    plt.figure(figsize=(8, 6))
    plt.rcParams["font.size"] = 20
    plt.boxplot(data, labels=labels_name)
    plt.grid(True, axis="y")


def plot_box_plot_all_ids(
    all_data: list[tuple[str, list[float]]],
    output_path: str,
):
    """
    全てのIDのcosine similaritiesを箱ひげ図で横並びで表示

    Args:
        all_data: [(feature_name, data), ...]のリスト
        output_path: 出力画像パス
    """
    plt.figure(figsize=(16, 8))
    plt.rcParams["font.size"] = 20

    # ラベルにデータ数を含める
    feature_names = [f"{item[0]}\n(n={len(item[1])})" for item in all_data]
    data_list = [item[1] for item in all_data]

    # 箱ひげ図を描画
    plt.boxplot(
        data_list,
        labels=feature_names,
        patch_artist=True,
        showmeans=True,
        meanprops=dict(marker="o", markerfacecolor="black", markeredgecolor="black", markersize=8),
        boxprops=dict(facecolor="white", color="black"),
        whiskerprops=dict(color="black"),
        capprops=dict(color="black"),
        medianprops=dict(color="orange"),
    )

    # グラフの装飾
    # plt.xlabel("ID", fontsize=14, fontweight="bold", labelpad=20)
    plt.ylabel("Cosine Similarity Mean", fontsize=14, fontweight="bold", labelpad=15)

    plt.xticks(rotation=0, ha="center")
    plt.grid(True, axis="y", alpha=0.3, linestyle="--")

    # y軸の範囲を設定 (-1.0 から 1.0)
    plt.ylim(-0.85, 0.85)
    plt.yticks(np.arange(-0.8, 0.9, 0.2))

    # 平均値の凡例を追加
    from matplotlib.lines import Line2D

    legend_elements = [
        Line2D([0], [0], marker="o", color="w", label="Mean", markerfacecolor="black", markersize=10),
    ]
    plt.legend(handles=legend_elements, loc="upper center", bbox_to_anchor=(0.5, -0.15), frameon=True)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"Saved: {output_path}")


def main():
    config = PathConfig()

    # feature_idの指定
    feature_info = [
        (1, "ID 1"),
        (5, "ID 2"),
        (14, "ID 3"),
        (84, "ID 4"),
        (92, "ID 5"),
        (139, "ID 6"),
    ]

    # データを収集
    all_id_data = []

    for i, (feature_id, feature_name) in enumerate(feature_info):
        id_num = i + 1
        # パス: output/ql_analysis/github/bachelor/id_{id_num}/id_{id_num}_similarity.json
        similarity_json_path = f"{config.output}/ql_analysis/github/bachelor/id_{id_num}/id_{id_num}_similarity.json"

        try:
            data = hayalab.read_json(similarity_json_path)
            # data.get("results") -> list of dicts with "mean" key
            means = [result.get("mean", 0.0) for result in data.get("results", [])]
            all_id_data.append((feature_name, means))
            print(f"Loaded {len(means)} data points for {feature_name}")
        except FileNotFoundError:
            print(f"File not found: {similarity_json_path}")
            all_id_data.append((feature_name, []))

    # 箱ひげ図を作成
    output_path = f"{config.output}/ql_analysis/github/bachelor/box_plot_all_ids.png"
    plot_box_plot_all_ids(all_id_data, output_path)


if __name__ == "__main__":
    main()
