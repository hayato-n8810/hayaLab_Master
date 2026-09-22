"""既知パターンの正解要素を含むクラスタを設計条件ごとに取り出し、検出性能を集計する。

正解集合は ``outputs/saner/PreAnalysis/base_only_hits.jsonl``（低速パターンが base 側にあり
head 側で消えたレコード）で、``target_id`` が既知パターン番号、``mb_id`` がレコード ID である。

``cases`` は、正解要素を 1 件でも含むクラスタについて、クラスタ ID・そのクラスタが含む正解要素・
それ以外のメンバー・phase2 の代表パターンを並べる。

``detection`` は、同じクラスタについて phase3 のクラスタパターンを ``MBDiff.json`` 全体へ
当てた結果（``outputs/saner/analysis/detection``）を正解集合と突き合わせ、precision / recall と
その内訳を出す。予測集合はクラスタパターンの ``base_hit_ids``、正解集合は当該 ``target_id`` の
``mb_id`` 全体であり、クラスタに含まれる正解要素だけではない。

出力:
    outputs/saner/analysis/known_patterns/cases/{condition}/pattern{N}_cluster.json
    outputs/saner/analysis/known_patterns/detection/pattern{N}/all_result.json
    outputs/saner/analysis/known_patterns/detection/pattern{N}/pickup_result.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import ijson

from hayalab.config import PathConfig

# --- Constants (hyperparameters tunable at the top of the file) ----
# 対象スコープ（phase2 / phase3 の出力ファイル名と対応する）
SCOPES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")

# 抽象度の水準
ABSTRACTION_LEVELS: tuple[str, ...] = ("alpha1", "alpha2")

# 一致度閾値の水準（detection の出力がある確定設定）
THRESHOLDS: tuple[float, ...] = (0.7, 0.9)

# pickup_result.json に載せる上位件数
PICKUP_TOP_N: int = 3


# --- Helpers (only those called many times) ------------------------
def _tau_suffix(tau: float) -> str:
    """閾値をディレクトリ名の接尾辞に直す。

    Args:
        tau: 一致度閾値。

    Returns:
        ``tau{NN}`` 形式の文字列。
    """
    return f"tau{round(tau * 10):02d}"


def _condition_key(tau: float, level: str, scope: str) -> str:
    """設計条件を識別する文字列を返す。

    Args:
        tau: 一致度閾値。
        level: 抽象度。
        scope: スコープ名。

    Returns:
        ``tau{NN}_{level}_{scope}`` 形式の文字列。
    """
    return f"{_tau_suffix(tau)}_{level}_{scope}"


def _ratio(numerator: int, denominator: int) -> float:
    """0 除算を 0.0 として比を返す。

    Args:
        numerator: 分子。
        denominator: 分母。

    Returns:
        比。分母が 0 なら 0.0。
    """
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    """適合率と再現率の調和平均を返す。

    Args:
        precision: 適合率。
        recall: 再現率。

    Returns:
        F1 値。両者が 0 なら 0.0。
    """
    return _ratio(2 * precision * recall, precision + recall) if (precision + recall) else 0.0


def _save_json(path: Path, payload: Any) -> None:
    """JSON を UTF-8 で書き出す。

    Args:
        path: 出力先。
        payload: 書き出す値。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数とパスの解決 ---
    parser = argparse.ArgumentParser(description="collect clusters covering known-pattern ground truth and score their detection")
    parser.add_argument("--scopes", nargs="+", default=list(SCOPES), help="対象スコープ")
    parser.add_argument("--levels", nargs="+", default=list(ABSTRACTION_LEVELS), help="抽象度の水準")
    parser.add_argument("--taus", type=float, nargs="+", default=list(THRESHOLDS), help="一致度閾値")
    parser.add_argument("--top-n", type=int, default=PICKUP_TOP_N, help="pickup_result.json に載せる上位件数")
    args = parser.parse_args()

    paths = PathConfig()
    truth_path = paths.outputs / "saner" / "PreAnalysis" / "base_only_hits.jsonl"
    detection_dir = paths.outputs / "saner" / "analysis" / "detection"
    phase2_dir = paths.outputs / "saner" / "approach" / "phase2"
    phase3_dir = paths.outputs / "saner" / "approach" / "phase3"
    output_dir = paths.outputs / "saner" / "analysis" / "known_patterns"

    if not truth_path.exists():
        raise SystemExit(f"正解ファイルがありません: {truth_path}")

    # --- Section 2: 正解集合の読み込み ---
    truth_ids: dict[int, set[int]] = defaultdict(set)
    with open(truth_path, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            truth_ids[int(record["target_id"])].add(int(record["mb_id"]))
    target_ids = sorted(truth_ids)
    print(f"scopes={args.scopes} levels={args.levels} taus={sorted(args.taus)} top_n={args.top_n}", flush=True)
    print(f"正解パターン {len(target_ids)} 件: " + ", ".join(f"pattern{t}={len(truth_ids[t])}" for t in target_ids), flush=True)

    # --- Section 3: 設計条件ごとの突き合わせ ---
    # 検出結果のレコードはパターン別にためて、最後に 1 ファイルへまとめる
    detection_records: dict[int, list[dict[str, Any]]] = {target: [] for target in target_ids}

    for tau in sorted(args.taus):
        for level in args.levels:
            for scope in args.scopes:
                condition = _condition_key(tau, level, scope)
                suffix = _tau_suffix(tau)
                representatives_path = phase2_dir / suffix / level / f"{scope}_representatives.jsonl"
                patterns_path = phase3_dir / suffix / level / f"{scope}_patterns.json"
                evaluation_path = detection_dir / suffix / level / f"{scope}_evaluation.json"

                if not representatives_path.exists():
                    print(f"[{condition}] phase2 の出力がないため飛ばす", flush=True)
                    continue

                # --- クラスタのメンバーと代表パターン ---
                members_of: dict[int, list[int]] = {}
                representative_of: dict[int, list[dict[str, Any]]] = {}
                with open(representatives_path, encoding="utf-8") as f:
                    for line in f:
                        payload = json.loads(line)
                        cluster_id = int(payload["cluster_id"])
                        members_of[cluster_id] = [int(member) for member in payload["members"]]
                        representative_of[cluster_id] = payload.get("patterns") or []

                # --- 正解要素を含むクラスタを target_id ごとに引く ---
                cluster_of_member: dict[int, int] = {}
                for cluster_id, members in members_of.items():
                    for member in members:
                        cluster_of_member[member] = cluster_id

                hit_clusters: dict[int, dict[int, set[int]]] = {}
                for target in target_ids:
                    per_cluster: dict[int, set[int]] = defaultdict(set)
                    for member in sorted(truth_ids[target]):
                        cluster_id = cluster_of_member.get(member)
                        if cluster_id is not None:
                            per_cluster[cluster_id].add(member)
                    hit_clusters[target] = dict(per_cluster)

                # --- cases の書き出し ---
                for target in target_ids:
                    clusters_payload = []
                    for cluster_id in sorted(hit_clusters[target]):
                        covered = sorted(hit_clusters[target][cluster_id])
                        clusters_payload.append(
                            {
                                "cluster_id": cluster_id,
                                "cluster_size": len(members_of[cluster_id]),
                                "base_only_hit_ids": covered,
                                "other_member_ids": sorted(set(members_of[cluster_id]) - set(covered)),
                                "patterns": representative_of[cluster_id],
                            }
                        )
                    _save_json(
                        output_dir / "cases" / condition / f"pattern{target}_cluster.json",
                        {
                            "condition": condition,
                            "scope": scope,
                            "level": level,
                            "threshold": tau,
                            "target_id": target,
                            "truth_size": len(truth_ids[target]),
                            "clusters": clusters_payload,
                        },
                    )
                print(f"[{condition}] cases 出力: " + ", ".join(f"pattern{t}={len(hit_clusters[t])}" for t in target_ids), flush=True)

                # --- 検出結果の突き合わせ ---
                if not evaluation_path.exists():
                    print(f"[{condition}] detection の出力がないため検出集計は飛ばす", flush=True)
                    continue

                # クラスタパターンの木構造（phase3 の root）
                root_of: dict[int, Any] = {}
                if patterns_path.exists():
                    with open(patterns_path, encoding="utf-8") as f:
                        for pattern in json.load(f)["patterns"]:
                            root_of[int(pattern["id"])] = pattern["root"]

                targets_of_cluster: dict[int, list[int]] = defaultdict(list)
                for target in target_ids:
                    for cluster_id in hit_clusters[target]:
                        targets_of_cluster[cluster_id].append(target)

                # base_hit_ids は大きくなりうるため、1 クラスタずつ読んで集計だけ残す
                with open(evaluation_path, "rb") as f:
                    for cluster in ijson.items(f, "clusters.item"):
                        cluster_id = int(cluster["cluster_id"])
                        if cluster_id not in targets_of_cluster:
                            continue
                        predicted = {int(hit_id) for hit_id in cluster["base_hit_ids"]}
                        for target in targets_of_cluster[cluster_id]:
                            truth = truth_ids[target]
                            true_positive = len(predicted & truth)
                            false_positive = len(predicted) - true_positive
                            false_negative = len(truth) - true_positive
                            precision = _ratio(true_positive, len(predicted))
                            recall = _ratio(true_positive, len(truth))
                            detection_records[target].append(
                                {
                                    "condition": condition,
                                    "scope": scope,
                                    "level": level,
                                    "threshold": tau,
                                    "cluster_id": cluster_id,
                                    "cluster_size": len(members_of[cluster_id]),
                                    "cluster_truth_size": len(hit_clusters[target][cluster_id]),
                                    "base_hits": len(predicted),
                                    "truth_size": len(truth),
                                    "precision": precision,
                                    "recall": recall,
                                    "f1": _f1(precision, recall),
                                    "true_positive": true_positive,
                                    "false_negative": false_negative,
                                    "false_positive": false_positive,
                                    "pattern": root_of.get(cluster_id),
                                }
                            )
                print(f"[{condition}] detection 集計: " + ", ".join(f"pattern{t}={len(hit_clusters[t])}" for t in target_ids), flush=True)

    # --- Section 4: 検出結果の書き出し ---
    for target in target_ids:
        records = sorted(detection_records[target], key=lambda record: (record["condition"], record["cluster_id"]))
        _save_json(
            output_dir / "detection" / f"pattern{target}" / "all_result.json",
            {"target_id": target, "truth_size": len(truth_ids[target]), "records": records},
        )
        _save_json(
            output_dir / "detection" / f"pattern{target}" / "pickup_result.json",
            {
                "target_id": target,
                "truth_size": len(truth_ids[target]),
                "top_n": args.top_n,
                "top_precision": sorted(records, key=lambda record: (-record["precision"], record["condition"], record["cluster_id"]))[: args.top_n],
                "top_recall": sorted(records, key=lambda record: (-record["recall"], record["condition"], record["cluster_id"]))[: args.top_n],
                "top_f1": sorted(records, key=lambda record: (-record["f1"], record["condition"], record["cluster_id"]))[: args.top_n],
            },
        )
        print(f"pattern{target}: 検出レコード {len(records)} 件", flush=True)
