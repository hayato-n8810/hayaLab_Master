"""既知パターンごとに、正解要素を含むクラスタ族 C_p と被覆率を設計条件別に算出する。

提案設計 (real) の指標に加え、クラスタメンバーをシャッフルしたランダムベースラインを N 回
反復して分布 (平均、標準偏差、95% 信頼区間、min、max) を算出する。

正解集合 ``G_p`` は ``outputs/saner/PreAnalysis/base_only_hits.jsonl`` の ``target_id == p``
のレコード (低速パターンが base 側にあり head 側で消えたもの) を用いる。

Real (提案設計) 指標:
    ``C_p``: G_p の要素を 1 件以上含むクラスタの総数。
    ``pure_C_p``: G_p の要素のみで構成された c_p の数。
    ``covered``: |G_p ∩ (∪C_p)|。
    ``R_union``: covered / |G_p|。
    ``R_max``: 最も多く G_p 要素を含む単一 c_p の G_p 要素数 / |G_p|。
    ``P_union``: covered / |∪C_p|。C_p の要素 (G_p 以外も含む全メンバー) のうち G_p の
        要素が占める割合。G_p に対する C_p の適合率 (precision)。
    ``uncovered``: どの c_p にも含まれなかった G_p 要素の数。

Random baseline:
    クラスタサイズ分布を保存したままメンバーを一様ランダムに再配置する。
    N 回反復して各指標 (``C_p`` / ``pure_C_p`` / ``covered`` / ``R_union`` / ``R_max`` /
    ``P_union`` / ``uncovered``) の分布を得る。信頼区間は反復値の 2.5% / 97.5% 分位から求める。

Mean intra-cluster Jaccard (設計条件単位、パターンに依存しない):
    各非孤立クラスタ (要素数 2 件以上) について、そのメンバー間の全ペア bigram Jaccard
    類似度の平均を計算し、条件内の非孤立クラスタ全体で集約 (mean) する。クラスタが
    ``G_p`` を機械的に「似ているもの」としてまとめているかどうかを、ランダムベースラインとは
    独立に検証する指標。bigram は phase1 のクラスタリングと同一の抽象度射影 (alpha1/alpha2)
    ・区切り記号除去規則を用いて phase0 の切り出しから再構成する。

クラスタは要素数 2 件以上のものを対象とする。要素数 1 のクラスタを含めると ∪C_p が
常に G_p を覆い R_union が自明に 1 になるため。ランダムベースラインもシャッフル後に
要素数 2 件以上のクラスタのみを対象とする。

出力:
    outputs/saner/analysis/clustering/README.md
    outputs/saner/analysis/clustering/summary.csv
    outputs/saner/analysis/clustering/design_conditions.csv
    outputs/saner/analysis/clustering/pattern{N}.json
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
from collections import defaultdict
from typing import Any

import ijson

from hayalab.config import PathConfig

# --- Constants (hyperparameters tunable at the top of the file) ----
# 対象スコープ (phase0 の出力ファイル名と対応する)
SCOPES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")

# 抽象度の水準
ABSTRACTION_LEVELS: tuple[str, ...] = ("alpha1", "alpha2")

# 一致度閾値の水準
THRESHOLDS: tuple[float, ...] = (0.7, 0.9)

# 対象とするクラスタの最小要素数
MIN_CLUSTER_SIZE: int = 2

# ランダムベースラインの反復数
NUM_RANDOM_ITERATIONS: int = 50

# 乱数シードの base (反復ごとに +1 する)
RANDOM_SEED_BASE: int = 20260918

# bigram の n（phase1 のクラスタリングと同一）
NGRAM_N: int = 2

# 前処理 hayalab.abst が割り当てる識別子（VAR / FUNCTION / KEY / CLASS の 4 種に連番）
PLACEHOLDER_PATTERN: re.Pattern[str] = re.compile(r"^(?:VAR|FUNCTION|KEY|CLASS)_\d+$")

# alpha2 で value を落とすリテラルノード名
LITERAL_NAMES: frozenset[str] = frozenset({"number", "string_fragment"})

# alpha2 で配下の value を落とすトリガーとなるノード名
REGEX_NODE_NAME: str = "regex"

# 親ノードの型から一意に定まる区切り記号（除去対象）。演算子は含めない
DELIMITER_NAMES: frozenset[str] = frozenset({"(", ")", "[", "]", "{", "}", ",", ";", ".", '"', "'", "`", ":", "=>", "${"})

# ラベル内で name と value を区切る文字
LABEL_SEPARATOR: str = ":"

# summary.csv の列
SUMMARY_COLUMNS: tuple[str, ...] = (
    "target_id",
    "G_p",
    "condition",
    "scope",
    "level",
    "threshold",
    "C_p_real",
    "C_p_random_mean",
    "C_p_random_ci_lo",
    "C_p_random_ci_hi",
    "R_union_real",
    "R_union_random_mean",
    "R_union_random_ci_lo",
    "R_union_random_ci_hi",
    "R_max_real",
    "R_max_random_mean",
    "R_max_random_ci_lo",
    "R_max_random_ci_hi",
    "P_union_real",
    "P_union_random_mean",
    "P_union_random_ci_lo",
    "P_union_random_ci_hi",
    "pure_C_p_real",
    "uncovered_real",
    "mean_intra_cluster_jaccard",
)

# design_conditions.csv の列
DESIGN_CONDITION_COLUMNS: tuple[str, ...] = (
    "condition",
    "scope",
    "level",
    "threshold",
    "non_singleton_clusters",
    "mean_intra_cluster_jaccard",
    "median_intra_cluster_jaccard",
    "std_intra_cluster_jaccard",
    "min_intra_cluster_jaccard",
    "max_intra_cluster_jaccard",
)

# 反復値を分布としてまとめる対象の指標
RANDOM_METRIC_KEYS: tuple[str, ...] = ("C_p", "pure_C_p", "covered", "R_union", "R_max", "P_union", "max_truth_members", "uncovered")


# --- Helpers (only those called many times) ------------------------
def _condition_name(scope: str, level: str, tau: float) -> str:
    """設計条件の表示名を返す。

    Args:
        scope: スコープ名。
        level: 抽象度。
        tau: 一致度閾値。

    Returns:
        ``{scope}/{level}/tau{NN}`` 形式の文字列。
    """
    return f"{scope}/{level}/tau{round(tau * 10):02d}"


def _percentile(values: list[float], p: float) -> float:
    """線形補間による分位数を返す。

    Args:
        values: 数値の列。
        p: 分位 (0-1)。

    Returns:
        分位数。空列の場合は 0.0。
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = p * (len(sorted_vals) - 1)
    lower = int(idx)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = idx - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


def _summarize(values: list[float]) -> dict[str, float]:
    """反復値の分布を平均、std、95% CI (2.5%/97.5% 分位)、min、max に集計する。

    Args:
        values: N 回の反復から得た値の列。

    Returns:
        ``mean`` / ``std`` / ``ci_lo`` / ``ci_hi`` / ``min`` / ``max`` を持つ dict。
    """
    if not values:
        return {"mean": 0.0, "std": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "min": 0.0, "max": 0.0}
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n if n > 1 else 0.0
    return {
        "mean": mean,
        "std": variance**0.5,
        "ci_lo": _percentile(values, 0.025),
        "ci_hi": _percentile(values, 0.975),
        "min": min(values),
        "max": max(values),
    }


def _compute_metrics_per_pattern(
    clusters: list[dict[str, Any]],
    truth_of: dict[int, set[int]],
    target_ids: list[int],
    min_cluster_size: int,
) -> dict[int, dict[str, Any]]:
    """1 回分のクラスタリング結果 (real or shuffled) から各パターンの C_p 系指標を計算する。

    Args:
        clusters: ``{"cluster_id", "size", "members"}`` の列。
        truth_of: パターン ID → G_p 集合。
        target_ids: 対象パターン ID の列。
        min_cluster_size: 対象とする最小クラスタ要素数。

    Returns:
        パターン ID → 指標 dict (``C_p`` / ``cluster_ids`` / ``clusters`` / ``pure_C_p`` /
        ``pure_cluster_ids`` / ``covered`` / ``R_union`` / ``max_cluster_id`` /
        ``max_truth_members`` / ``R_max`` / ``union_members`` / ``P_union`` /
        ``uncovered`` / ``uncovered_ids``)。
    """
    family_of: dict[int, list[dict[str, Any]]] = defaultdict(list)
    covered_of: dict[int, set[int]] = defaultdict(set)
    union_of: dict[int, set[int]] = defaultdict(set)
    for cluster in clusters:
        if cluster["size"] < min_cluster_size:
            continue
        members = set(cluster["members"])
        for target_id in target_ids:
            inside = members & truth_of[target_id]
            if not inside:
                continue
            family_of[target_id].append(
                {
                    "cluster_id": cluster["cluster_id"],
                    "size": cluster["size"],
                    "truth_members": len(inside),
                    "pure": len(inside) == cluster["size"],
                }
            )
            covered_of[target_id] |= inside
            # C_p (∪C_p) は G_p 以外のメンバーも含む、family クラスタの全メンバーの和集合
            union_of[target_id] |= members

    result: dict[int, dict[str, Any]] = {}
    for target_id in target_ids:
        truth = truth_of[target_id]
        clusters_for_p = sorted(family_of[target_id], key=lambda r: r["cluster_id"])
        covered = covered_of[target_id]
        union_members = union_of[target_id]
        uncovered = sorted(truth - covered)
        pure_ids = [r["cluster_id"] for r in clusters_for_p if r["pure"]]
        largest = max(clusters_for_p, key=lambda r: (r["truth_members"], -r["cluster_id"]), default=None)
        result[target_id] = {
            "C_p": len(clusters_for_p),
            "cluster_ids": [r["cluster_id"] for r in clusters_for_p],
            "clusters": clusters_for_p,
            "pure_C_p": len(pure_ids),
            "pure_cluster_ids": pure_ids,
            "covered": len(covered),
            "R_union": len(covered) / len(truth) if truth else 0.0,
            "max_cluster_id": largest["cluster_id"] if largest else None,
            "max_truth_members": largest["truth_members"] if largest else 0,
            "R_max": (largest["truth_members"] / len(truth)) if largest and truth else 0.0,
            "union_members": len(union_members),
            "P_union": (len(covered) / len(union_members)) if union_members else 0.0,
            "uncovered": len(uncovered),
            "uncovered_ids": uncovered,
        }
    return result


def _shuffle_memberships(clusters: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    """クラスタサイズ分布を保存したままメンバーを一様ランダムに再配置する。

    Args:
        clusters: ``{"cluster_id", "size", "members"}`` の列。
        rng: 乱数生成器。

    Returns:
        メンバーがシャッフルされた新しい clusters リスト。cluster_id と size は不変で、
        members のみ入れ替わる。
    """
    all_ids = [mb_id for c in clusters for mb_id in c["members"]]
    rng.shuffle(all_ids)
    shuffled: list[dict[str, Any]] = []
    idx = 0
    for c in clusters:
        size = c["size"]
        shuffled.append({"cluster_id": c["cluster_id"], "size": size, "members": all_ids[idx : idx + size]})
        idx += size
    return shuffled


def _regex_descendant_indices(nodes: list[dict[str, Any]]) -> frozenset[int]:
    """``regex`` ノードの子孫の ``origin_index`` 集合を返す（phase1 と同一規則）。

    Args:
        nodes: ノード payload の列。

    Returns:
        regex 配下ノードの origin_index 集合。
    """
    regex_indices = {node["origin_index"] for node in nodes if node["name"] == REGEX_NODE_NAME}
    if not regex_indices:
        return frozenset()
    return frozenset(node["origin_index"] for node in nodes if regex_indices.intersection(node["parent"]))


def _label(node: dict[str, Any], level: str, regex_descendants: frozenset[int]) -> str:
    """ノードの射影ラベルを返す（phase1 と同一規則）。

    Args:
        node: ノード payload。
        level: 抽象度（``"alpha1"`` / ``"alpha2"``）。
        regex_descendants: :func:`_regex_descendant_indices` の結果。alpha2 でのみ参照する。

    Returns:
        ``name`` または ``name:value`` 形式のラベル。
    """
    name = node["name"]
    value = node["value"]
    if PLACEHOLDER_PATTERN.match(value):
        return name
    if level == "alpha2" and (name in LITERAL_NAMES or node["origin_index"] in regex_descendants):
        return name
    return f"{name}{LABEL_SEPARATOR}{value}"


def _record_bigrams(nodes: list[dict[str, Any]], level: str) -> frozenset[tuple[str, str]]:
    """1 レコード分の切り出しノード列から bigram 集合を返す（phase1 と同一規則）。

    Args:
        nodes: 切り出し結果の 1 レコード分のノード列（区切り記号を含みうる）。
        level: 抽象度（``"alpha1"`` / ``"alpha2"``）。

    Returns:
        preorder 順の隣接 2 ラベルからなる bigram の frozenset。トークンが 2 未満なら空集合。
    """
    kept = [node for node in nodes if node["name"] not in DELIMITER_NAMES]
    if len(kept) < NGRAM_N:
        return frozenset()
    kept.sort(key=lambda node: node["origin_index"])
    regex_descendants = _regex_descendant_indices(kept) if level == "alpha2" else frozenset()
    tokens = [_label(node, level, regex_descendants) for node in kept]
    return frozenset(tuple(tokens[i : i + NGRAM_N]) for i in range(len(tokens) - NGRAM_N + 1))


def _bigram_jaccard(left: frozenset[tuple[str, str]], right: frozenset[tuple[str, str]]) -> float:
    """2 つの bigram 集合の Jaccard 係数を返す。

    Args:
        left: 比較元の bigram 集合。
        right: 比較先の bigram 集合。

    Returns:
        ``|left ∩ right| / |left ∪ right|``。両者空なら 1.0。
    """
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def _mean_intra_cluster_jaccard(members: list[int], bigram_of: dict[int, frozenset[tuple[str, str]]]) -> float | None:
    """1 クラスタ内の全メンバーペアについて bigram Jaccard の平均を返す。

    Args:
        members: クラスタのメンバー mb_id 列。
        bigram_of: mb_id → bigram 集合。

    Returns:
        全ペアの平均 Jaccard。bigram 集合を持つメンバーが 2 件未満なら ``None``。
    """
    sets = [bigram_of[mb_id] for mb_id in members if mb_id in bigram_of]
    if len(sets) < 2:
        return None
    total = 0.0
    count = 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            total += _bigram_jaccard(sets[i], sets[j])
            count += 1
    return total / count if count else None


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数とパスの解決 ---
    parser = argparse.ArgumentParser(description="cluster family C_p, R_union/R_max/P_union, and mean intra-cluster Jaccard (real vs random baseline)")
    parser.add_argument("--scopes", nargs="+", default=list(SCOPES), help="対象スコープ")
    parser.add_argument("--levels", nargs="+", default=list(ABSTRACTION_LEVELS), help="抽象度の水準")
    parser.add_argument("--taus", type=float, nargs="+", default=list(THRESHOLDS), help="一致度閾値")
    parser.add_argument("--random-iters", type=int, default=NUM_RANDOM_ITERATIONS, help="ランダムベースラインの反復数")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED_BASE, help="乱数シードの base (反復ごとに増加)")
    args = parser.parse_args()

    config = PathConfig()
    truth_path = config.outputs / "saner" / "PreAnalysis" / "base_only_hits.jsonl"
    phase0_dir = config.outputs / "saner" / "approach" / "phase0"
    phase1_dir = config.outputs / "saner" / "approach" / "phase1"
    output_dir = config.outputs / "saner" / "analysis" / "clustering"

    for path in (truth_path, phase0_dir, phase1_dir):
        if not path.exists():
            raise FileNotFoundError(f"入力が見つかりません: {path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: 正解集合の読み込み ---
    truth_of: dict[int, set[int]] = defaultdict(set)
    with open(truth_path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            truth_of[row["target_id"]].add(row["mb_id"])
    target_ids = sorted(truth_of)
    print(f"正解集合: {truth_path}")
    for target_id in target_ids:
        print(f"  P{target_id}: |G_p| = {len(truth_of[target_id])}")
    print(f"クラスタは要素数 {MIN_CLUSTER_SIZE} 件以上")
    print(f"ランダムベースライン: {args.random_iters} 反復\n")

    # --- Section 3: 全条件のクラスタを読み込み、スコープごとに必要な mb_id を集める ---
    clusters_of: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    wanted_ids_by_scope: dict[str, set[int]] = defaultdict(set)
    for tau in sorted(args.taus):
        suffix = f"tau{round(tau * 10):02d}"
        for level in args.levels:
            for scope in args.scopes:
                cluster_path = phase1_dir / suffix / level / f"{scope}_clusters.jsonl"
                if not cluster_path.exists():
                    print(f"[SKIP] {cluster_path} が無い")
                    continue
                with open(cluster_path, encoding="utf-8") as f:
                    clusters = [json.loads(line) for line in f]
                clusters_of[(scope, level, tau)] = clusters
                for cluster in clusters:
                    if cluster["size"] >= MIN_CLUSTER_SIZE:
                        wanted_ids_by_scope[scope].update(cluster["members"])
    print(f"読み込み済み設計条件: {len(clusters_of)}")
    for scope, ids in wanted_ids_by_scope.items():
        print(f"  {scope}: 非孤立クラスタのメンバー {len(ids)} 件")

    # --- Section 4: phase0 の切り出しをスコープごとに 1 度だけ読み、bigram 集合を作る ---
    # level は射影規則の違いに過ぎず phase0 の I/O には影響しないため、生ノードをスコープ単位で
    # キャッシュしてから alpha1 / alpha2 それぞれの bigram を組み立てる (I/O を 1/len(levels) に抑える)。
    bigram_of: dict[tuple[str, str], dict[int, frozenset[tuple[str, str]]]] = {}
    for scope, wanted in wanted_ids_by_scope.items():
        raw_nodes_of: dict[int, list[dict[str, Any]]] = {}
        with open(phase0_dir / f"{scope}.json", "rb") as f:
            for record in ijson.items(f, "item"):
                if record["id"] in wanted:
                    raw_nodes_of[record["id"]] = record["nodes"]
        print(f"phase0 読み込み: {scope} ({len(raw_nodes_of)} / {len(wanted)} 件)")
        for level in args.levels:
            bigram_of[(scope, level)] = {mb_id: _record_bigrams(nodes, level) for mb_id, nodes in raw_nodes_of.items()}

    # --- Section 5: 設計条件ごとに real / random / mean intra-cluster jaccard を計算 ---
    conditions_of: dict[int, list[dict[str, Any]]] = defaultdict(list)
    design_conditions: list[dict[str, Any]] = []
    iter_counter = 0

    for (scope, level, tau), clusters in sorted(clusters_of.items(), key=lambda item: (item[0][2], item[0][1], item[0][0])):
        condition = _condition_name(scope, level, tau)

        # 提案設計での指標
        real_metrics = _compute_metrics_per_pattern(clusters, truth_of, target_ids, MIN_CLUSTER_SIZE)

        # クラスタ内平均 bigram Jaccard（パターンに依存しない、条件単位の指標）
        bigrams = bigram_of[(scope, level)]
        jaccard_values = [value for value in (_mean_intra_cluster_jaccard(cluster["members"], bigrams) for cluster in clusters if cluster["size"] >= MIN_CLUSTER_SIZE) if value is not None]
        jaccard_summary = {
            "non_singleton_clusters": len(jaccard_values),
            "mean": statistics.mean(jaccard_values) if jaccard_values else 0.0,
            "median": statistics.median(jaccard_values) if jaccard_values else 0.0,
            "std": statistics.pstdev(jaccard_values) if len(jaccard_values) > 1 else 0.0,
            "min": min(jaccard_values) if jaccard_values else 0.0,
            "max": max(jaccard_values) if jaccard_values else 0.0,
        }
        design_conditions.append({"condition": condition, "scope": scope, "level": level, "threshold": tau, **jaccard_summary})

        # ランダムベースラインの分布 (target_id → 指標名 → 反復値のリスト)
        random_samples: dict[int, dict[str, list[float]]] = {target_id: {key: [] for key in RANDOM_METRIC_KEYS} for target_id in target_ids}
        for _ in range(args.random_iters):
            rng = random.Random(args.seed + iter_counter)
            iter_counter += 1
            shuffled = _shuffle_memberships(clusters, rng)
            iter_metrics = _compute_metrics_per_pattern(shuffled, truth_of, target_ids, MIN_CLUSTER_SIZE)
            for target_id in target_ids:
                for key in RANDOM_METRIC_KEYS:
                    random_samples[target_id][key].append(float(iter_metrics[target_id][key]))

        # 条件別のレコードを組み立てる (real はトップレベル、random は入れ子)
        for target_id in target_ids:
            conditions_of[target_id].append(
                {
                    "condition": condition,
                    "scope": scope,
                    "level": level,
                    "threshold": tau,
                    **real_metrics[target_id],
                    "random": {key: _summarize(random_samples[target_id][key]) for key in RANDOM_METRIC_KEYS},
                    "mean_intra_cluster_jaccard": jaccard_summary["mean"],
                }
            )

        print(f"集計: {condition}  (real + random × {args.random_iters}, mean intra-cluster jaccard = {jaccard_summary['mean']:.4f} over {jaccard_summary['non_singleton_clusters']} clusters)")

    # --- Section 6: パターンごとに書き出し ---
    summary: list[dict[str, Any]] = []
    for target_id in target_ids:
        conditions = conditions_of[target_id]
        if not conditions:
            continue
        with open(output_dir / f"pattern{target_id}.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "target_id": target_id,
                    "G_p": len(truth_of[target_id]),
                    "min_cluster_size": MIN_CLUSTER_SIZE,
                    "num_random_iterations": args.random_iters,
                    "conditions": conditions,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        print(f"Written: {output_dir / f'pattern{target_id}.json'}")

        for row in conditions:
            summary.append(
                {
                    "target_id": target_id,
                    "G_p": len(truth_of[target_id]),
                    "condition": row["condition"],
                    "scope": row["scope"],
                    "level": row["level"],
                    "threshold": row["threshold"],
                    "C_p_real": row["C_p"],
                    "C_p_random_mean": row["random"]["C_p"]["mean"],
                    "C_p_random_ci_lo": row["random"]["C_p"]["ci_lo"],
                    "C_p_random_ci_hi": row["random"]["C_p"]["ci_hi"],
                    "R_union_real": row["R_union"],
                    "R_union_random_mean": row["random"]["R_union"]["mean"],
                    "R_union_random_ci_lo": row["random"]["R_union"]["ci_lo"],
                    "R_union_random_ci_hi": row["random"]["R_union"]["ci_hi"],
                    "R_max_real": row["R_max"],
                    "R_max_random_mean": row["random"]["R_max"]["mean"],
                    "R_max_random_ci_lo": row["random"]["R_max"]["ci_lo"],
                    "R_max_random_ci_hi": row["random"]["R_max"]["ci_hi"],
                    "P_union_real": row["P_union"],
                    "P_union_random_mean": row["random"]["P_union"]["mean"],
                    "P_union_random_ci_lo": row["random"]["P_union"]["ci_lo"],
                    "P_union_random_ci_hi": row["random"]["P_union"]["ci_hi"],
                    "pure_C_p_real": row["pure_C_p"],
                    "uncovered_real": row["uncovered"],
                    "mean_intra_cluster_jaccard": row["mean_intra_cluster_jaccard"],
                }
            )

    with open(output_dir / "summary.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(SUMMARY_COLUMNS))
        writer.writeheader()
        writer.writerows(summary)
    print(f"Written: {output_dir / 'summary.csv'}")

    # --- Section 7: 設計条件単位の指標 (mean intra-cluster jaccard) を書き出し ---
    design_conditions.sort(key=lambda row: (row["threshold"], row["level"], row["scope"]))
    with open(output_dir / "design_conditions.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(DESIGN_CONDITION_COLUMNS),
        )
        writer.writeheader()
        for row in design_conditions:
            writer.writerow(
                {
                    "condition": row["condition"],
                    "scope": row["scope"],
                    "level": row["level"],
                    "threshold": row["threshold"],
                    "non_singleton_clusters": row["non_singleton_clusters"],
                    "mean_intra_cluster_jaccard": row["mean"],
                    "median_intra_cluster_jaccard": row["median"],
                    "std_intra_cluster_jaccard": row["std"],
                    "min_intra_cluster_jaccard": row["min"],
                    "max_intra_cluster_jaccard": row["max"],
                }
            )
    print(f"Written: {output_dir / 'design_conditions.csv'}")

    # --- Section 8: README の書き出し ---
    index = [
        "# G_p 集約指標 — 提案設計とランダムベースラインの比較",
        "",
        "各設計条件について、`|C_p|` / `R_union` / `R_max` / `P_union` を提案設計 (real) とランダムベースラインで比較する。",
        f"ランダムベースラインはクラスタサイズ分布を保存したままメンバーを一様ランダムに再配置し、{args.random_iters} 回反復して分布を得る。",
        f"クラスタは要素数 {MIN_CLUSTER_SIZE} 件以上を対象とする。要素数 1 のクラスタを含めると `∪C_p` が常に `G_p` を覆い、",
        "`R_union` が自明に 1 になるため。ランダムベースラインもシャッフル後に要素数 2 件以上のクラスタのみを対象とする。",
        "",
        "併せて、パターンに依存しない設計条件単位の指標として Mean intra-cluster Jaccard も算出する。",
        "各非孤立クラスタについてメンバー間の全ペア bigram Jaccard 類似度の平均を取り、条件内の全非孤立クラスタで",
        "さらに平均したもの。クラスタが機械的に「似ているもの」の集団になっているかを、G_p を参照せずに検証する。",
        "",
        "正解集合 `G_p` は `outputs/saner/PreAnalysis/base_only_hits.jsonl` の `target_id` 別集合。",
        "",
        "## 出力",
        "",
        "| ファイル | 内容 |",
        "|---|---|",
        "| `pattern{N}.json` | パターン N の設計条件別 real / random 指標、および条件ごとの `mean_intra_cluster_jaccard` |",
        "| `summary.csv` | 全パターン × 全条件の要約 (real 値と random の mean / ci_lo / ci_hi、および `mean_intra_cluster_jaccard`) |",
        "| `design_conditions.csv` | 条件ごと 1 行の Mean intra-cluster Jaccard（mean/median/std/min/max、パターン非依存） |",
        "",
        "## `pattern{N}.json` の項目 (per condition)",
        "",
        "| 項目 | 定義 |",
        "|---|---|",
        "| `C_p` | 提案設計での `G_p` 要素を含むクラスタ数 |",
        "| `pure_C_p` | `G_p` のみで構成された `c_p` の数 (`pure_cluster_ids` に ID) |",
        "| `covered` | `\\|G_p ∩ (∪C_p)\\|` |",
        "| `R_union` | `covered / \\|G_p\\|` |",
        "| `max_cluster_id` / `max_truth_members` | 最も多く `G_p` 要素を含む単一 `c_p` の ID と `G_p` 要素数 |",
        "| `R_max` | `max_truth_members / \\|G_p\\|` |",
        "| `union_members` | `∪C_p` の全メンバー数（`G_p` 以外の要素も含む） |",
        "| `P_union` | `covered / union_members`。`G_p` に対する `C_p` の適合率 (precision) |",
        "| `uncovered` / `uncovered_ids` | どの `c_p` にも含まれなかった `G_p` 要素の数と ID |",
        "| `clusters` | `c_p` の一覧 (`cluster_id` / `size` / `truth_members` / `pure`) |",
        "| `random.C_p` | ランダムベースラインの分布 (`mean` / `std` / `ci_lo` / `ci_hi` / `min` / `max`) |",
        "| `random.R_union` / `random.R_max` / `random.P_union` / ... | 同上、他の指標 |",
        "| `mean_intra_cluster_jaccard` | その設計条件の Mean intra-cluster Jaccard（パターンに依存せず全条件で同値） |",
        "",
        "## `summary.csv` の項目",
        "",
        "`target_id`, `condition`, `scope`, `level`, `threshold`, `G_p`, 各指標の real 値、",
        "ランダムベースラインの `mean` / `ci_lo` (2.5%) / `ci_hi` (97.5%)、および `mean_intra_cluster_jaccard`。",
        "",
        "## `design_conditions.csv` の項目",
        "",
        "`condition`, `scope`, `level`, `threshold`, `non_singleton_clusters`（対象クラスタ数）、",
        "および Mean intra-cluster Jaccard の `mean` / `median` / `std` / `min` / `max`。",
        "",
        "## 読み方",
        "",
        "- `C_p_real` < `C_p_random_ci_lo` なら、提案設計は `G_p` をランダムより少数のクラスタに集中している。",
        "- `R_union_real` > `R_union_random_ci_hi` なら、提案設計はランダムより `G_p` を網羅的に集約している。",
        "  ただし非孤立クラスタが `G_p` 以外の要素も広く含む場合、ランダムでも `R_union` が高くなりうるため、",
        "  この指標だけで有効性を主張するのは避け、`R_max` や `P_union` と併せて判断する。",
        "- `R_max_real` > `R_max_random_ci_hi` なら、提案設計は `G_p` を単一クラスタに集中している。",
        "- `P_union_real` > `P_union_random_ci_hi` なら、`C_p` に混入する `G_p` 以外の要素がランダムより少なく、",
        "  適合率の観点で提案設計が優れている。",
        "- `mean_intra_cluster_jaccard` が高いほど、クラスタは bigram 表現上で互いに類似したコード断片の",
        "  集団になっている。この指標はランダムベースラインとの比較ではなく、クラスタの均質性そのものを見る。",
        "- 95% 信頼区間はランダム反復の 2.5% / 97.5% 分位から求めた分布ベースの区間。",
    ]
    with open(output_dir / "README.md", "w", encoding="utf-8") as f:
        f.write("\n".join(index) + "\n")
    print(f"Written: {output_dir / 'README.md'}")
