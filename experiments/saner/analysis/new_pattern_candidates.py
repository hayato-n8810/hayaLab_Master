"""既知パターンに該当しないクラスタを新規パターン候補として取り出し、群ごとの最小代表値を選ぶ。

候補は、phase2 の代表値・``outputs/saner/analysis/detection`` の検出結果・
``outputs/saner/PreAnalysis/base_only_hits.jsonl`` の既知正解を突き合わせ、設計条件ごとに
クラスタ要素数の多い順で並べたものである。検出集合は ``base_only_hit_ids``（代表値が base に
当たり head に当たらなかったレコード）を指す。

pickup は、12 の設計条件を横断してプールした代表値を根ノードの型と具体値の集合の組で群にまとめ、
群ごとにノード数が最小のものを採ったものである。

出力:
    outputs/saner/analysis/new_patterns/{condition}.json
    outputs/saner/analysis/new_patterns/summary.csv
    outputs/saner/analysis/new_patterns/pickup/minimal_patterns.json
    outputs/saner/analysis/new_patterns/pickup/summary.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import ijson

from hayalab.config import PathConfig

# --- Constants (hyperparameters tunable at the top of the file) ----
# 対象スコープ（phase2 / detection の出力ファイル名と対応する）
SCOPES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")

# 抽象度の水準
ABSTRACTION_LEVELS: tuple[str, ...] = ("alpha1", "alpha2")

# 一致度閾値の水準（detection の出力がある確定設定）
THRESHOLDS: tuple[float, ...] = (0.7, 0.9)

# 候補として採るクラスタの最小要素数
MIN_CLUSTER_SIZE: int = 2

# 候補として採る代表値の最小ノード数
MIN_NODES: int = 2

# summary.csv に設計条件ごとに載せる上位件数
SUMMARY_TOP_N: int = 20


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


def _count_nodes(node: dict[str, Any]) -> int:
    """パターン木のノード数を数える。

    Args:
        node: パターン木のノード。

    Returns:
        自身を含むノード数。
    """
    return 1 + sum(_count_nodes(child) for child in node.get("children") or [])


def _collect_values(node: dict[str, Any]) -> list[str]:
    """パターン木に現れる具体値を集める。

    Args:
        node: パターン木のノード。

    Returns:
        出現順の具体値。重複はそのまま残す。
    """
    values = [node["value"]] if node.get("value") is not None else []
    for child in node.get("children") or []:
        values.extend(_collect_values(child))
    return values


def _flatten(node: dict[str, Any]) -> str:
    """パターン木を 1 行の文字列に直す。

    Args:
        node: パターン木のノード。

    Returns:
        ``name="value"`` と ``name(child child)`` を組み合わせた表現。
    """
    text = node["name"]
    if node.get("value") is not None:
        text += f'="{node["value"]}"'
    children = node.get("children") or []
    if children:
        text += "(" + " ".join(_flatten(child) for child in children) + ")"
    return text


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


def _save_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    """CSV を UTF-8 で書き出す。

    Args:
        path: 出力先。
        header: 見出し行。
        rows: データ行。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数とパスの解決 ---
    parser = argparse.ArgumentParser(description="collect new-pattern candidate clusters and pick the minimal representative per group")
    parser.add_argument("--scopes", nargs="+", default=list(SCOPES), help="対象スコープ")
    parser.add_argument("--levels", nargs="+", default=list(ABSTRACTION_LEVELS), help="抽象度の水準")
    parser.add_argument("--taus", type=float, nargs="+", default=list(THRESHOLDS), help="一致度閾値")
    parser.add_argument("--min-cluster-size", type=int, default=MIN_CLUSTER_SIZE, help="候補として採るクラスタの最小要素数")
    parser.add_argument("--min-nodes", type=int, default=MIN_NODES, help="候補として採る代表値の最小ノード数")
    parser.add_argument("--summary-top-n", type=int, default=SUMMARY_TOP_N, help="summary.csv に設計条件ごとに載せる上位件数")
    args = parser.parse_args()

    paths = PathConfig()
    truth_path = paths.outputs / "saner" / "PreAnalysis" / "base_only_hits.jsonl"
    detection_dir = paths.outputs / "saner" / "analysis" / "detection"
    phase2_dir = paths.outputs / "saner" / "approach" / "phase2"
    output_dir = paths.outputs / "saner" / "analysis" / "new_patterns"

    if not truth_path.exists():
        raise SystemExit(f"正解ファイルがありません: {truth_path}")

    print(f"scopes={args.scopes} levels={args.levels} taus={sorted(args.taus)}", flush=True)

    # --- Section 2: 既知パターンの正解集合（全パターンの和集合） ---
    truth_ids: set[int] = set()
    with open(truth_path, encoding="utf-8") as f:
        for line in f:
            truth_ids.add(int(json.loads(line)["mb_id"]))
    print(f"既知パターンの正解 {len(truth_ids)} 件", flush=True)

    # --- Section 3: 設計条件ごとの候補抽出 ---
    # pickup 用に 12 条件を横断してプールする
    pooled: list[dict[str, Any]] = []
    summary_rows: list[list[Any]] = []

    for tau in sorted(args.taus):
        for level in args.levels:
            for scope in args.scopes:
                condition = _condition_key(tau, level, scope)
                suffix = _tau_suffix(tau)
                representatives_path = phase2_dir / suffix / level / f"{scope}_representatives.jsonl"
                evaluation_path = detection_dir / suffix / level / f"{scope}_evaluation.json"

                if not representatives_path.exists() or not evaluation_path.exists():
                    print(f"[{condition}] phase2 または detection の出力がないため飛ばす", flush=True)
                    continue

                # --- クラスタの代表値 ---
                cluster_of: dict[int, dict[str, Any]] = {}
                with open(representatives_path, encoding="utf-8") as f:
                    for line in f:
                        payload = json.loads(line)
                        components = payload.get("patterns") or []
                        members = [int(member) for member in payload["members"]]
                        if not components or len(members) < args.min_cluster_size:
                            continue
                        nodes = sum(_count_nodes(component) for component in components)
                        if nodes < args.min_nodes:
                            continue
                        cluster_of[int(payload["cluster_id"])] = {
                            "size": len(members),
                            "members": members,
                            "components": components,
                            "nodes": nodes,
                        }

                # --- 検出結果の突き合わせ（base_only_hit_ids は大きいため 1 クラスタずつ読む）---
                candidates: list[dict[str, Any]] = []
                with open(evaluation_path, "rb") as f:
                    for cluster in ijson.items(f, "clusters.item"):
                        cluster_id = int(cluster["cluster_id"])
                        entry = cluster_of.get(cluster_id)
                        if entry is None:
                            continue
                        detected = {int(hit_id) for hit_id in cluster["base_only_hit_ids"]}
                        if detected & truth_ids:
                            continue
                        components = entry["components"]
                        candidates.append(
                            {
                                "cluster_id": cluster_id,
                                "size": entry["size"],
                                "nodes": entry["nodes"],
                                "detection": len(detected),
                                "base_hits": int(cluster["base_hits"]),
                                "members": entry["members"],
                                "representative": components,
                                "representative_flat": " ".join(_flatten(component) for component in components),
                            }
                        )

                candidates.sort(key=lambda candidate: (-candidate["size"], candidate["cluster_id"]))
                _save_json(
                    output_dir / f"{condition}.json",
                    {
                        "condition": condition,
                        "scope": scope,
                        "level": level,
                        "threshold": tau,
                        "candidates_total": len(candidates),
                        "candidates": candidates,
                    },
                )

                for rank, candidate in enumerate(candidates[: args.summary_top_n], start=1):
                    summary_rows.append(
                        [
                            condition,
                            rank,
                            candidate["cluster_id"],
                            candidate["size"],
                            candidate["nodes"],
                            candidate["detection"],
                            candidate["base_hits"],
                            candidate["representative_flat"],
                        ]
                    )

                # --- pickup 用のプール（単一の連結木・具体値あり・メンバーに既知正解を含まない）---
                for candidate in candidates:
                    components = candidate["representative"]
                    if len(components) != 1:
                        continue
                    values = _collect_values(components[0])
                    if not values:
                        continue
                    if set(candidate["members"]) & truth_ids:
                        continue
                    pooled.append(
                        {
                            "root": components[0]["name"],
                            "values": sorted(set(values)),
                            "cluster_id": candidate["cluster_id"],
                            "members": candidate["members"],
                            "condition": f"{scope}/{level}/{suffix}",
                            "nodes": candidate["nodes"],
                            "size": candidate["size"],
                            "detection": candidate["detection"],
                            "pattern": components[0],
                            "representative_flat": candidate["representative_flat"],
                        }
                    )

                print(f"[{condition}] 候補 {len(candidates)} 件", flush=True)

    _save_csv(
        output_dir / "summary.csv",
        ["condition", "rank", "cluster_id", "size", "nodes", "detection", "base_hits", "representative"],
        summary_rows,
    )

    # --- Section 4: 群ごとの最小代表値 ---
    # (根ノードの型, 具体値の集合) で群にまとめる
    grouped: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
    for entry in pooled:
        grouped.setdefault((entry["root"], tuple(entry["values"])), []).append(entry)

    picked: list[dict[str, Any]] = []
    for (root, values), entries in grouped.items():
        minimal = min(entries, key=lambda entry: (entry["nodes"], -entry["detection"], entry["condition"], entry["cluster_id"]))
        picked.append(
            {
                "root": root,
                "values": list(values),
                "variants": len({entry["representative_flat"] for entry in entries}),
                "cluster_id": minimal["cluster_id"],
                "members": minimal["members"],
                "condition": minimal["condition"],
                "nodes": minimal["nodes"],
                "size": minimal["size"],
                "detection": minimal["detection"],
                "pattern": minimal["pattern"],
                "representative_flat": minimal["representative_flat"],
            }
        )

    picked.sort(key=lambda entry: (-entry["variants"], entry["nodes"], entry["root"], entry["values"]))
    _save_json(
        output_dir / "pickup" / "minimal_patterns.json",
        {
            "order": "variants",
            "min_nodes": args.min_nodes,
            "distinct_representatives": len({entry["representative_flat"] for entry in pooled}),
            "groups": len(picked),
            "patterns": picked,
        },
    )
    _save_csv(
        output_dir / "pickup" / "summary.csv",
        ["rank", "nodes", "root", "values", "variants", "cluster_id", "condition", "size", "detection", "representative", "members"],
        [
            [
                rank,
                entry["nodes"],
                entry["root"],
                " ".join(entry["values"]),
                entry["variants"],
                entry["cluster_id"],
                entry["condition"],
                entry["size"],
                entry["detection"],
                entry["representative_flat"],
                " ".join(str(member) for member in entry["members"]),
            ]
            for rank, entry in enumerate(picked, start=1)
        ],
    )

    print(f"pickup: プール {len(pooled)} 件 / 群 {len(picked)} 件", flush=True)
