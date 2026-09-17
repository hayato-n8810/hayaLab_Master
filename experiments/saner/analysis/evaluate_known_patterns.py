"""既知パターンの要素がクラスタにどれだけ集約されたかを、パターン別に集計する。

正解集合は ``outputs/saner/PreAnalysis/base_only_hits.jsonl``（低速パターンが base 側にあり
head 側で消えたレコード）。``target_id`` ごとにディレクトリを切って出力する。

クラスタは要素数 2 件以上のものを対象とする。要素数 1 のクラスタに落ちた正解要素は
「孤立」として別に数える。

正解要素の行き先は 4 通りに尽き、合計が正解要素総数に一致する。

* 純粋クラスタ内 — そのクラスタが正解要素のみからなる
* 混在クラスタ内 — そのクラスタに正解以外の要素も含まれる
* 孤立          — 要素数 1 のクラスタに落ちた
* 不在          — 切り出しが空などでクラスタリング対象外

代表と ``slow_patterns.json`` の一致は、代表のパターン仕様を擬似 AST に展開して
``find_tree_matches`` を適用することで判定する。仕様は ``begin`` / ``end`` と ``code`` を
持たないため、葉ごとに擬似トークンを割り当てて擬似コードを合成する。同じ ``bind`` を
持つ葉には同じトークンを与えるため、仕様側の ``bind``（ソーステキストの同一性）が正しく働く。

* 値が定まっている葉  — そのトークンを ``value`` とする
* ``bind`` を持つ葉   — グループ共通のトークン
* いずれでもない葉    — 一意のトークン（仕様が値を要求すれば一致しない）

一致は「代表が仕様の制約をすべて備えている」ことを意味する。一致しない場合は代表が仕様より
一般的（汎化しすぎ、または必要な値が pin されていない）と読める。逆向き（仕様が代表より
一般的か）は仕様側に ``*`` や選言や ``match: "descendant"`` があり擬似 AST 化できないため、
代表のノード数と仕様のノード数の比で代用する。

代表が空のクラスタも一致率の分母に含める（一致しなかったものとして数える）。

``cut 被覆`` は、正解パターンの一致範囲と切り出し範囲の関係を表す文脈情報である。
``base_only_hits.jsonl`` の ``snippet`` を ``base_code`` 中から探して一致範囲を復元し、
切り出しノードの ``begin`` / ``end`` と比較する。

* 重なり   — 一致範囲と重なる切り出しノードがある（変更がパターンに触れている）
* 範囲を覆う — 一致範囲全体を覆う切り出しノードがある（パターン全体が切り出しに入っている）

``範囲を覆う`` が成り立たないとき、切り出しはパターンの一部しか持たないため、代表が仕様を
再現しえない。仕様一致率を読む際の前提になる。

出力:
    outputs/saner/analysis/known_patterns/README.md
    outputs/saner/analysis/known_patterns/pattern{N}/summary.md
    outputs/saner/analysis/known_patterns/pattern{N}/cells.csv
    outputs/saner/analysis/known_patterns/pattern{N}/clusters.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from typing import Any

import ijson

from hayalab.classes.gumtree import ASTNode, TreePattern
from hayalab.config import PathConfig
from hayalab.gumtree import find_tree_matches, load_tree_patterns

# --- Constants (hyperparameters tunable at the top of the file) ----
# 対象スコープ（phase0 / phase1 / phase2 のファイル名と対応する）
SCOPES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")

# 抽象度の水準
ABSTRACTION_LEVELS: tuple[str, ...] = ("alpha1", "alpha2")

# 一致度閾値の水準
THRESHOLDS: tuple[float, ...] = (0.6, 0.7, 0.8, 0.9)

# 擬似トークンを囲む文字（実コードに現れない形にする）
TOKEN_OPEN: str = "<"
TOKEN_CLOSE: str = ">"

# summary.md の表に出す列
SUMMARY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("cell", "設計セル"),
    ("pure_clusters", "純粋クラスタ数"),
    ("pure_members", "純粋クラスタの要素数"),
    ("pure_max", "純粋クラスタ最大"),
    ("mixed_clusters", "混在クラスタ数"),
    ("mixed_truth_members", "混在内の正解数"),
    ("mixed_other_members", "混在内の非正解数"),
    ("isolated", "孤立"),
    ("max_cluster_coverage", "最大クラスタ被覆率"),
    ("spec_match", "仕様一致クラスタ数"),
    ("spec_match_rate", "仕様一致率"),
)


# --- Helpers (only those called many times) ------------------------
def _emit_pseudo(spec: dict[str, Any], ancestors: list[int], nodes: list[ASTNode | None], pieces: list[str], cursor: int, counter: list[int]) -> int:
    """パターン仕様を preorder に展開し、擬似 AST と擬似コードを組み立てる。

    Args:
        spec: ノード仕様（``name`` / ``value`` / ``bind`` / ``children``）。
        ancestors: 根から直上までの祖先インデックス列。
        nodes: 構築中の ASTNode 列（preorder）。
        pieces: 構築中の擬似コード断片。
        cursor: 現在の擬似コード上の位置。
        counter: 一意トークンの採番に使う 1 要素リスト。

    Returns:
        この部分木を書き終えた後の擬似コード上の位置。
    """
    index = len(nodes)
    nodes.append(None)
    begin = cursor

    children = spec.get("children") or []
    if children:
        for child in children:
            cursor = _emit_pseudo(child, [*ancestors, index], nodes, pieces, cursor, counter)
    else:
        if spec.get("bind") is not None:
            body = f"b:{spec['bind']}"
        elif spec.get("value") is not None:
            body = f"v:{spec['value']}"
        else:
            counter[0] += 1
            body = f"u:{counter[0]}"
        token = f"{TOKEN_OPEN}{body}{TOKEN_CLOSE}"
        pieces.append(token)
        cursor += len(token)

    value = spec.get("value") or ""
    nodes[index] = ASTNode(begin=begin, end=cursor, label=spec["name"], name=spec["name"], value=value, parent=list(ancestors))
    return cursor


def _pseudo_ast(spec: dict[str, Any]) -> tuple[list[ASTNode], str]:
    """パターン仕様を擬似 AST と擬似コードに変換する。

    Args:
        spec: 代表パターンの根ノード仕様。

    Returns:
        ``(preorder の ASTNode 列, 擬似コード)``。
    """
    nodes: list[ASTNode | None] = []
    pieces: list[str] = []
    _emit_pseudo(spec, [], nodes, pieces, 0, [0])
    return [node for node in nodes if node is not None], "".join(pieces)


def _spec_size(spec: dict[str, Any]) -> int:
    """パターン仕様のノード数を返す。

    Args:
        spec: ノード仕様。

    Returns:
        自身を含む仕様ノードの総数。
    """
    return 1 + sum(_spec_size(child) for child in spec.get("children") or [])


def _matches_spec(patterns: list[dict[str, Any]], known: TreePattern) -> bool:
    """代表の成分のいずれかが既知パターンにマッチするかを判定する。

    Args:
        patterns: 代表の成分ごとのパターン仕様。
        known: 照合する既知パターン。

    Returns:
        いずれかの成分がマッチすれば True。成分が無ければ False。
    """
    for component in patterns:
        nodes, code = _pseudo_ast(component)
        if find_tree_matches(nodes, code, known, snippet_limit=1):
            return True
    return False


def _cell_name(scope: str, level: str, tau: float) -> str:
    """設計セルの表示名を返す。

    Args:
        scope: スコープ名。
        level: 抽象度。
        tau: 一致度閾値。

    Returns:
        ``{scope}/{level}/tau{NN}`` 形式の文字列。
    """
    return f"{scope}/{level}/tau{round(tau * 10):02d}"


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数とパスの解決 ---
    parser = argparse.ArgumentParser(description="known pattern aggregation analysis over phase1/phase2 outputs")
    parser.add_argument("--scopes", nargs="+", default=list(SCOPES), help="対象スコープ")
    parser.add_argument("--levels", nargs="+", default=list(ABSTRACTION_LEVELS), help="抽象度の水準")
    parser.add_argument("--taus", type=float, nargs="+", default=list(THRESHOLDS), help="一致度閾値")
    args = parser.parse_args()

    config = PathConfig()
    truth_path = config.outputs / "saner" / "PreAnalysis" / "base_only_hits.jsonl"
    spec_path = config.experiments / "saner" / "PreAnalysis" / "patterns" / "slow_patterns.json"
    phase0_dir = config.outputs / "saner" / "approach" / "phase0"
    phase1_dir = config.outputs / "saner" / "approach" / "phase1"
    phase2_dir = config.outputs / "saner" / "approach" / "phase2"
    analysis_dir = config.outputs / "saner" / "analysis" / "known_patterns"

    for path in (truth_path, spec_path, phase1_dir, phase2_dir):
        if not path.exists():
            raise FileNotFoundError(f"入力が見つかりません: {path}")
    analysis_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: 正解集合の読み込みと一致範囲の復元 ---
    truth_of: dict[int, set[int]] = defaultdict(set)
    span_of: dict[tuple[int, int], tuple[int, int]] = {}
    unresolved = 0
    with open(truth_path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            target_id, mb_id = row["target_id"], row["mb_id"]
            truth_of[target_id].add(mb_id)
            position = row["base_code"].find(row["snippet"])
            if position < 0:
                unresolved += 1
                continue
            span_of.setdefault((target_id, mb_id), (position, position + len(row["snippet"])))

    labelled = {mb_id for members in truth_of.values() for mb_id in members}
    target_ids = sorted(truth_of)
    print(f"正解集合: パターン {len(target_ids)} 種 / 異なり mb_id {len(labelled)} / 一致範囲を復元できなかった行 {unresolved}")
    for target_id in target_ids:
        print(f"  P{target_id}: {len(truth_of[target_id])} 件")

    with open(spec_path, encoding="utf-8") as f:
        spec_data = json.load(f)
    known_of = {pattern.pattern_id: pattern for pattern in load_tree_patterns(spec_data)}
    spec_sizes = {entry["id"]: _spec_size(entry["root"]) for entry in spec_data["patterns"]}

    # --- Section 3: 一致範囲と切り出し範囲の関係（スコープごと） ---
    overlap_of: dict[str, dict[tuple[int, int], bool]] = {}
    contain_of: dict[str, dict[tuple[int, int], bool]] = {}
    for scope in args.scopes:
        cut_spans: dict[int, list[tuple[int, int]]] = {}
        with open(phase0_dir / f"{scope}.json", "rb") as f:
            for record in ijson.items(f, "item"):
                if record["id"] in labelled:
                    cut_spans[record["id"]] = [(node["begin"], node["end"]) for node in record["nodes"]]
        overlap_of[scope] = {}
        contain_of[scope] = {}
        for key, (begin, end) in span_of.items():
            spans = cut_spans.get(key[1], [])
            overlap_of[scope][key] = any(node_begin < end and begin < node_end for node_begin, node_end in spans)
            contain_of[scope][key] = any(node_begin <= begin and end <= node_end for node_begin, node_end in spans)
        print(f"cut 被覆を判定: {scope}")

    # --- Section 4: セルごとに集計する ---
    rows_of: dict[int, list[dict[str, Any]]] = defaultdict(list)
    detail_of: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for scope in args.scopes:
        for level in args.levels:
            for tau in sorted(args.taus):
                cell = _cell_name(scope, level, tau)
                suffix = f"tau{round(tau * 10):02d}/{level}"
                cluster_path = phase1_dir / suffix / f"{scope}_clusters.jsonl"
                representative_path = phase2_dir / suffix / f"{scope}_representatives.jsonl"
                if not cluster_path.exists():
                    print(f"[SKIP] {cell}: {cluster_path} が無い")
                    continue

                clusters = [json.loads(line) for line in open(cluster_path, encoding="utf-8")]
                representatives: dict[int, dict[str, Any]] = {}
                if representative_path.exists():
                    for line in open(representative_path, encoding="utf-8"):
                        payload = json.loads(line)
                        representatives[payload["cluster_id"]] = payload

                clustered = {mb_id for cluster in clusters for mb_id in cluster["members"]}
                for target_id in target_ids:
                    truth = truth_of[target_id]
                    known = known_of.get(target_id)
                    counts = {
                        "pure_clusters": 0,
                        "pure_members": 0,
                        "pure_max": 0,
                        "mixed_clusters": 0,
                        "mixed_truth_members": 0,
                        "mixed_other_members": 0,
                        "mixed_other_known": 0,
                        "mixed_other_unlabeled": 0,
                        "isolated": 0,
                        "spec_match": 0,
                        "spec_match_pure": 0,
                        "rep_missing": 0,
                    }
                    largest = 0
                    rep_nodes: list[int] = []

                    for cluster in clusters:
                        members = set(cluster["members"])
                        inside = members & truth
                        if not inside:
                            continue
                        if cluster["size"] < 2:
                            counts["isolated"] += len(inside)
                            continue

                        others = members - truth
                        pure = not others
                        largest = max(largest, len(inside))
                        if pure:
                            counts["pure_clusters"] += 1
                            counts["pure_members"] += len(inside)
                            counts["pure_max"] = max(counts["pure_max"], len(inside))
                        else:
                            counts["mixed_clusters"] += 1
                            counts["mixed_truth_members"] += len(inside)
                            counts["mixed_other_members"] += len(others)
                            counts["mixed_other_known"] += len(others & labelled)
                            counts["mixed_other_unlabeled"] += len(others - labelled)

                        payload = representatives.get(cluster["cluster_id"])
                        components = payload["patterns"] if payload else []
                        if not components:
                            counts["rep_missing"] += 1
                        else:
                            rep_nodes.append(payload["node_count"])
                        matched = bool(components) and known is not None and _matches_spec(components, known)
                        if matched:
                            counts["spec_match"] += 1
                            if pure:
                                counts["spec_match_pure"] += 1

                        detail_of[target_id].append(
                            {
                                "cell": cell,
                                "cluster_id": cluster["cluster_id"],
                                "size": cluster["size"],
                                "truth_members": len(inside),
                                "other_known": len(others & labelled),
                                "other_unlabeled": len(others - labelled),
                                "purity": len(inside) / cluster["size"],
                                "rep_nodes": payload["node_count"] if payload else 0,
                                "rep_coverage": payload["coverage"] if payload else 0.0,
                                "spec_match": matched,
                            }
                        )

                    total = len(truth)
                    with_truth = counts["pure_clusters"] + counts["mixed_clusters"]
                    row = {
                        "cell": cell,
                        "scope": scope,
                        "level": level,
                        "threshold": tau,
                        "truth_total": total,
                        "truth_overlap": sum(1 for mb_id in truth if overlap_of[scope].get((target_id, mb_id), False)),
                        "truth_contained": sum(1 for mb_id in truth if contain_of[scope].get((target_id, mb_id), False)),
                        "absent": len(truth - clustered),
                        "clusters_with_truth": with_truth,
                        **counts,
                        "max_cluster_coverage": largest / total if total else 0.0,
                        "spec_match_rate": counts["spec_match"] / with_truth if with_truth else 0.0,
                        "spec_match_rate_pure": counts["spec_match_pure"] / counts["pure_clusters"] if counts["pure_clusters"] else 0.0,
                        "rep_nodes_mean": sum(rep_nodes) / len(rep_nodes) if rep_nodes else 0.0,
                        "spec_nodes": spec_sizes.get(target_id, 0),
                    }
                    rows_of[target_id].append(row)
                print(f"集計: {cell}")

    # --- Section 5: パターンごとに書き出す ---
    columns = [key for key, _ in SUMMARY_COLUMNS]
    for target_id in target_ids:
        rows = rows_of[target_id]
        if not rows:
            continue
        pattern_dir = analysis_dir / f"pattern{target_id}"
        pattern_dir.mkdir(parents=True, exist_ok=True)

        with open(pattern_dir / "cells.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

        with open(pattern_dir / "clusters.jsonl", "w", encoding="utf-8") as f:
            for detail in detail_of[target_id]:
                f.write(json.dumps(detail, ensure_ascii=False) + "\n")

        best = max(rows, key=lambda row: (row["max_cluster_coverage"], row["spec_match_rate"]))
        key = known_of[target_id].key if target_id in known_of else f"pattern_{target_id}"
        lines = [
            f"# P{target_id} `{key}`",
            "",
            f"正解要素 **{rows[0]['truth_total']}** 件（`base_only_hits.jsonl` の `target_id={target_id}`）。",
            f"仕様のノード数 {rows[0]['spec_nodes']}。",
            "",
            "## 切り出しとの関係（スコープ別）",
            "",
            "| スコープ | 重なりあり | 範囲を覆う |",
            "|---|---|---|",
        ]
        for scope in args.scopes:
            sample = next((row for row in rows if row["scope"] == scope), None)
            if sample:
                lines.append(
                    f"| {scope} | {sample['truth_overlap']} ({sample['truth_overlap'] / sample['truth_total']:.1%}) | {sample['truth_contained']} ({sample['truth_contained'] / sample['truth_total']:.1%}) |"
                )
        lines += [
            "",
            "`範囲を覆う` が低いスコープでは、切り出しがパターンの一部しか持たないため、",
            "代表が仕様を再現しえない。仕様一致率はその前提で読む。",
            "",
            "## 設計セル別",
            "",
            "| " + " | ".join(label for _, label in SUMMARY_COLUMNS) + " |",
            "|" + "---|" * len(SUMMARY_COLUMNS),
        ]
        for row in rows:
            cells = []
            for column in columns:
                value = row[column]
                cells.append(f"{value:.3f}" if isinstance(value, float) else str(value))
            lines.append("| " + " | ".join(cells) + " |")
        lines += [
            "",
            "## 最大クラスタ被覆率が最良のセル",
            "",
            f"- セル: `{best['cell']}`",
            f"- 最大クラスタ被覆率: {best['max_cluster_coverage']:.3f}（正解 {rows[0]['truth_total']} 件中 最大 {round(best['max_cluster_coverage'] * best['truth_total'])} 件が 1 クラスタ）",
            f"- 正解を含むクラスタ数: {best['clusters_with_truth']}（純粋 {best['pure_clusters']} / 混在 {best['mixed_clusters']}）",
            f"- 孤立: {best['isolated']} / 不在: {best['absent']}",
            f"- 混在の非正解要素: {best['mixed_other_members']}（別パターン {best['mixed_other_known']} / ラベルなし {best['mixed_other_unlabeled']}）",
            f"- 仕様一致: {best['spec_match']}/{best['clusters_with_truth']} = {best['spec_match_rate']:.3f}（純粋のみ {best['spec_match_pure']}/{best['pure_clusters']}）",
            f"- 代表が空: {best['rep_missing']}（一致率の分母に含む）",
            f"- 代表のノード数 平均 {best['rep_nodes_mean']:.1f} / 仕様 {best['spec_nodes']}",
            "",
            "## 読み方",
            "",
            "- **正解要素の行き先**は `純粋クラスタの要素数 + 混在内の正解数 + 孤立 + 不在 = 正解要素総数` に一致する。",
            "- **純粋クラスタ数** が 1 に近いほど 1 つにまとまっている。数が多いのは分割を意味する。",
            "- **最大クラスタ被覆率** は最大の塊が正解全体に占める割合。セル間・パターン間の比較にはこれを使う。",
            "- **混在内の非正解数** の内訳が `別パターン` なら手法がパターンを区別できていない、",
            "  `ラベルなし` なら未知パターンか汎用イディオムの混入を示す。",
            "- **仕様一致率** は代表が `slow_patterns.json` の制約をすべて備えた割合。",
            "  代表が空のクラスタも分母に含める（一致しなかったものとして数える）。",
            "  一致しないのは代表が仕様より一般的（汎化しすぎ／必要な値が pin されていない）なとき。",
            "- **代表のノード数 / 仕様のノード数** が大きいほど過剰特定。仕様との一般性の差はこの比で読む。",
            "- `clusters.jsonl` に正解要素を含むクラスタの明細（純度・代表のノード数・一致可否）がある。",
        ]
        with open(pattern_dir / "summary.md", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Written: {pattern_dir}")

    index = [
        "# 既知パターンの集約分析",
        "",
        "`outputs/saner/PreAnalysis/base_only_hits.jsonl` を正解集合とし、phase1 のクラスタと",
        "phase2 の代表が既知パターンをどれだけ集約・再現できたかをパターン別に集計した。",
        "",
        "クラスタは要素数 2 件以上を対象とする。要素数 1 に落ちた正解要素は「孤立」として数える。",
        "",
        "## パターン",
        "",
        "| パターン | key | 正解要素数 | ディレクトリ |",
        "|---|---|---|---|",
    ]
    for target_id in target_ids:
        if not rows_of[target_id]:
            continue
        key = known_of[target_id].key if target_id in known_of else f"pattern_{target_id}"
        index.append(f"| P{target_id} | `{key}` | {len(truth_of[target_id])} | [pattern{target_id}/summary.md](pattern{target_id}/summary.md) |")
    index += [
        "",
        "## 指標の定義",
        "",
        "| 指標 | 定義 |",
        "|---|---|",
        "| 純粋クラスタ | 正解要素のみからなるクラスタ |",
        "| 混在クラスタ | 正解以外の要素も含むクラスタ |",
        "| 孤立 | 要素数 1 のクラスタに落ちた正解要素 |",
        "| 不在 | 切り出しが空などでクラスタリング対象外になった正解要素 |",
        "| 最大クラスタ被覆率 | 最大の塊に入った正解要素数 / 正解要素総数 |",
        "| 仕様一致率 | 代表が `slow_patterns.json` にマッチしたクラスタ数 / 正解を含むクラスタ数 |",
        "| 重なり | パターンの一致範囲と重なる切り出しノードがある |",
        "| 範囲を覆う | パターンの一致範囲全体を覆う切り出しノードがある |",
        "",
        "仕様一致は、代表のパターン仕様を擬似 AST に展開して `find_tree_matches` を適用して判定する。",
        "同じ `bind` を持つ葉には同じ擬似トークンを与えるため、仕様側の `bind` が正しく働く。",
        "代表が空のクラスタも分母に含める。",
    ]
    with open(analysis_dir / "README.md", "w", encoding="utf-8") as f:
        f.write("\n".join(index) + "\n")
    print(f"Written: {analysis_dir / 'README.md'}")
