"""Phase 2: phase1 の各クラスタから共通部分木を取り、代表パターンを作る。

スコープ 3 種 × 抽象度 2 水準の 6 組を並列に処理し、各組で全閾値のクラスタを扱う。

代表の作り方は 5 段からなる。

1. 骨格 — 各メンバーの切り出しを仮想ルート下の順序付き森とし、子列を LCS で対応付けながら
   メンバー ID 昇順に畳み込む。対応しない子は代表に含めない。骨格は全メンバーが共有する構造になる。
2. 値 — 骨格の各ノードについて、全メンバーの射影ラベルを数える。過半数を占める値があれば
   その値を制約とし、なければ ``name`` のみとする。
3. 参照 — 射影で失われる変数の同一性を補う。値が定まらなかったノードのうち、全メンバーで
   プレースホルダ識別子であるものを、メンバーごとの生 ``value`` の並び（参照シグネチャ）で
   グループ化し、2 ノード以上のグループに ``bind`` を張る。1 ノードだけの ``bind`` は
   照合対象を持たず制約にならないため張らない。
4. 階層 — 切り出しで祖先が欠落すると、骨格の辺が元 AST の親子関係と一致しなくなる。preorder では
   祖先鎖に沿ってインデックスが単調増加するため、子の祖先列のうち骨格上の親より大きいものが
   挟まった祖先にあたる。1 メンバーでも挟まっていれば ``match: "descendant"`` を付ける。
   ``descendant`` は緩和であり挟まっていないメンバーにも当たるので、これで全メンバーを覆える。
5. 出力 — ``slow_patterns.json`` と同じノード仕様（``name`` / ``value`` / ``bind`` / ``match`` / ``children``）に整形する。

射影ラベルは phase1 と同一の規則を用いる。

| 条件 | alpha1 のラベル | alpha2 のラベル |
|---|---|---|
| ``value`` がプレースホルダ識別子（``VAR_1`` 等） | ``name`` | ``name`` |
| ``name`` が ``number`` / ``string_fragment`` | ``name:value`` | ``name`` |
| ``regex`` ノードの子孫 | ``name:value`` | ``name`` |
| 上記以外（API 名・演算子・非終端） | ``name:value`` | ``name:value`` |

したがって alpha1 の代表は具体的なリテラルを保持し、alpha2 の代表は保持しない。

区切り記号は phase1 と同様に除去するため、代表を照合に用いる際は ``ignore_names`` を
指定する必要がある。値はサマリに記録する。

切り出しは森であり、仮想ルートの子が複数になりうる。パターン仕様は単一の根を取るため、
成分ごとに 1 件の仕様を出力する。

代表は過半数ルールで値を決めるため、全メンバーを覆うとは限らない。覆う割合 ``coverage`` と
``retention``（代表のノード数 / 最小メンバーのノード数）はセル単位でサマリに集計する。

出力:
    outputs/saner/approach/phase2/tau{NN}/{level}/{scope}_representatives.jsonl
    outputs/saner/approach/phase2/representative_summary.json

出力 JSONL の 1 行は ``{"cluster_id", "size", "members", "patterns"}``。
``patterns`` は成分ごとのノード仕様であり、パターン仕様の ``root`` に相当する。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, NamedTuple

import ijson

from hayalab.config import PathConfig

# --- Constants (hyperparameters tunable at the top of the file) ----
# 対象スコープ（phase0 の出力ファイル名と対応する）
SCOPES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")

# 一致度閾値の水準（phase1 の出力ディレクトリ名と対応する）
THRESHOLDS: tuple[float, ...] = (0.6, 0.7, 0.8, 0.9)

# 抽象度の水準
ABSTRACTION_LEVELS: tuple[str, ...] = ("alpha1", "alpha2")

# 仮想ルートのラベル
VIRTUAL_ROOT_NAME: str = "⊤"

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

# bind 名の接頭辞
BIND_PREFIX: str = "ref"


class CutNode(NamedTuple):
    """切り出しノードのうち、代表の構成に必要な情報のみを保持する。"""

    origin_index: int
    name: str
    value: str
    parent: tuple[int, ...]


# --- Helpers (only those called many times) ------------------------
def _regex_descendant_indices(nodes: list[CutNode]) -> frozenset[int]:
    """``regex`` ノードの子孫の ``origin_index`` 集合を返す。

    ``regex`` ノード自身は含めない。判定は切り出し内に存在する ``regex`` ノードに限る。

    Args:
        nodes: 1 レコード分のノード列。

    Returns:
        regex 配下ノードの origin_index 集合。
    """
    regex_indices = {node.origin_index for node in nodes if node.name == REGEX_NODE_NAME}
    if not regex_indices:
        return frozenset()
    return frozenset(node.origin_index for node in nodes if regex_indices.intersection(node.parent))


def _label(node: CutNode, level: str, regex_descendants: frozenset[int]) -> str:
    """ノードの射影ラベルを返す（phase1 と同一規則）。

    Args:
        node: 切り出しノード。
        level: 抽象度（``"alpha1"`` / ``"alpha2"``）。
        regex_descendants: :func:`_regex_descendant_indices` の結果。alpha2 でのみ参照する。

    Returns:
        ``name`` または ``name:value`` 形式のラベル。
    """
    if PLACEHOLDER_PATTERN.match(node.value):
        return node.name
    if level == "alpha2" and (node.name in LITERAL_NAMES or node.origin_index in regex_descendants):
        return node.name
    return f"{node.name}{LABEL_SEPARATOR}{node.value}"


def _build_tree(nodes: list[CutNode], member: int) -> dict[str, Any]:
    """切り出しノード列を仮想ルート付きの順序付き木にする。

    切り出しにより祖先が欠落しうるため、存在する最近接の祖先を親とする。
    入力が ``origin_index`` 昇順（preorder）であることを利用し、親を先に構築する。

    Args:
        nodes: 1 レコード分のノード列（origin_index 昇順）。
        member: クラスタ内でのメンバー番号。

    Returns:
        ``{"name", "children", "origins"}`` を持つ木。``origins`` はメンバー番号から
        そのメンバーの origin_index への対応。
    """
    position = {node.origin_index: index for index, node in enumerate(nodes)}
    root: dict[str, Any] = {"name": VIRTUAL_ROOT_NAME, "children": [], "origins": {}}
    built: list[dict[str, Any]] = []

    for node in nodes:
        made: dict[str, Any] = {"name": node.name, "children": [], "origins": {member: node.origin_index}}
        built.append(made)
        holder = root
        for ancestor in reversed(node.parent):
            if ancestor in position:
                holder = built[position[ancestor]]
                break
        holder["children"].append(made)

    return root


def _lcs_pairs(left: list[str], right: list[str]) -> list[tuple[int, int]]:
    """2 つのラベル列の最長共通部分列を、対応 index の組で返す。

    Args:
        left: 比較元のラベル列。
        right: 比較先のラベル列。

    Returns:
        ``(left の index, right の index)`` の昇順列。
    """
    rows, columns = len(left), len(right)
    table = [[0] * (columns + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(columns - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if left[i] == right[j] else max(table[i + 1][j], table[i][j + 1])

    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < rows and j < columns:
        if left[i] == right[j]:
            pairs.append((i, j))
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def _align(accumulated: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """2 つの木を ``name`` の一致で対応付け、共通部分のみを残す。

    子列は :func:`_lcs_pairs` で対応付け、対応した組だけを再帰的に処理する。

    Args:
        accumulated: 畳み込み中の木。
        other: 追加するメンバーの木。

    Returns:
        共通部分の木。``origins`` は両者の和。
    """
    origins = dict(accumulated["origins"])
    origins.update(other["origins"])
    left_children = accumulated["children"]
    right_children = other["children"]
    children = [_align(left_children[i], right_children[j]) for i, j in _lcs_pairs([child["name"] for child in left_children], [child["name"] for child in right_children])]
    return {"name": accumulated["name"], "children": children, "origins": origins}


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    """木を preorder で平坦化する（仮想ルートを含む）。

    Args:
        node: 木の根。

    Returns:
        preorder 順のノード列。
    """
    collected = [node]
    for child in node["children"]:
        collected.extend(_walk(child))
    return collected


def _mark_descendant(node: dict[str, Any], parent: dict[str, Any] | None, lookup: list[dict[int, CutNode]]) -> None:
    """骨格の辺が元 AST でも直接の親子かを判定し、``descendant`` を付ける。

    切り出しで祖先が欠落すると :func:`_build_tree` が最近接の存在する祖先へ付け替えるため、
    骨格の辺は元 AST の親子関係と一致しないことがある。preorder では祖先鎖に沿って
    インデックスが単調増加するので、子の祖先列のうち親より大きいものが挟まった祖先になる。

    1 メンバーでも祖先が挟まっていれば直接の子として照合できないため、``descendant`` を付ける。
    ``descendant`` は緩和であり挟まっていないメンバーにも当たるので、これで全メンバーを覆える。

    Args:
        node: 骨格ノード。
        parent: 骨格上の親ノード。根の場合は ``None``。
        lookup: メンバーごとの ``origin_index`` からノードへの対応。
    """
    if parent is not None and parent["name"] != VIRTUAL_ROOT_NAME:
        node["descendant"] = any(any(ancestor > parent["origins"][member] for ancestor in lookup[member][node["origins"][member]].parent) for member in node["origins"])
    for child in node["children"]:
        _mark_descendant(child, node, lookup)


def _spec_of(node: dict[str, Any]) -> dict[str, Any]:
    """骨格ノードを ``slow_patterns.json`` 形式のノード仕様に整形する。

    Args:
        node: 値・bind・descendant の決定済みの骨格ノード。

    Returns:
        ``name`` / ``value`` / ``bind`` / ``match`` / ``children`` を持つ仕様 dict。
    """
    spec: dict[str, Any] = {"name": node["name"]}
    if node.get("value") is not None:
        spec["value"] = node["value"]
    if node.get("bind") is not None:
        spec["bind"] = node["bind"]
    if node.get("descendant"):
        spec["match"] = "descendant"
    if node["children"]:
        spec["children"] = [_spec_of(child) for child in node["children"]]
    return spec


def _representative(members: list[int], node_lists: list[list[CutNode]], level: str) -> dict[str, Any]:
    """1 クラスタ分の代表パターンと、サマリ用の指標を作る。

    Args:
        members: メンバーの mb_id（昇順）。
        node_lists: メンバーごとの切り出しノード列（members と同じ並び）。
        level: 抽象度（``"alpha1"`` / ``"alpha2"``）。

    Returns:
        成分ごとのノード仕様 ``patterns`` と、セル集計に用いる指標を持つ dict。
    """
    lookup = [{node.origin_index: node for node in nodes} for nodes in node_lists]
    regex_descendants = [_regex_descendant_indices(nodes) if level == "alpha2" else frozenset() for nodes in node_lists]

    # 骨格: メンバー ID 昇順に畳み込む
    skeleton = _build_tree(node_lists[0], 0)
    for member in range(1, len(node_lists)):
        skeleton = _align(skeleton, _build_tree(node_lists[member], member))

    body = _walk(skeleton)[1:]
    total = len(node_lists)

    # 値: 過半数を占める射影ラベルがあれば採用する
    no_majority = 0
    for node in body:
        origins = node["origins"]
        counts = Counter(_label(lookup[member][origins[member]], level, regex_descendants[member]) for member in origins)
        # 同数は辞書順で決定的に選ぶ
        top, count = max(sorted(counts.items()), key=lambda item: item[1])
        node["label"] = top if count * 2 > total else None
        # 非終端やキーワードは value が name と一致するため、name の制約と重複する分は書かない
        value = top.split(LABEL_SEPARATOR, 1)[1] if node["label"] and LABEL_SEPARATOR in top else None
        node["value"] = None if value == node["name"] else value
        if node["label"] is None:
            no_majority += 1

    # 参照: 値が定まらず全メンバーでプレースホルダのノードを、生 value の並びでまとめる
    signatures: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for node in body:
        node["bind"] = None
        if node["value"] is not None:
            continue
        raws = tuple(lookup[member][node["origins"][member]].value for member in sorted(node["origins"]))
        if all(PLACEHOLDER_PATTERN.match(raw) for raw in raws):
            signatures[raws].append(node)
    bind_groups = 0
    for signature in sorted(signatures):
        group = signatures[signature]
        if len(group) < 2:
            continue
        for node in group:
            node["bind"] = f"{BIND_PREFIX}{bind_groups + 1}"
        bind_groups += 1

    # 被覆: 値制約を全て満たすメンバーの割合
    covered = 0
    for member in range(total):
        if all(node["label"] is None or _label(lookup[member][node["origins"][member]], level, regex_descendants[member]) == node["label"] for node in body):
            covered += 1

    # 階層: 元 AST で祖先が挟まる辺に descendant を付ける
    _mark_descendant(skeleton, None, lookup)

    minimum = min(len(nodes) for nodes in node_lists)
    return {
        "patterns": [_spec_of(child) for child in skeleton["children"]],
        "node_count": len(body),
        "retention": len(body) / minimum if minimum else 0.0,
        "no_majority": no_majority,
        "bind_groups": bind_groups,
        "descendant_edges": sum(1 for node in body if node.get("descendant")),
        "coverage": covered / total,
    }


def _process_cell(scope: str, level: str, phase0_dir: Path, phase1_dir: Path, phase2_dir: Path, taus: list[float]) -> list[dict[str, Any]]:
    """1 組（スコープ × 抽象度）の全閾値について代表を作る。

    ProcessPoolExecutor のワーカーから呼ばれる。スコープの切り出しは 1 度だけ読み、
    必要なレコードのノードのみを保持する。

    Args:
        scope: スコープ名（``sigma_1`` / ``sigma_2`` / ``sigma_3``）。
        level: 抽象度（``"alpha1"`` / ``"alpha2"``）。
        phase0_dir: phase0 の出力ディレクトリ。
        phase1_dir: phase1 の出力ディレクトリ（``tau{NN}/{level}`` を含む）。
        phase2_dir: ``tau{NN}/{level}`` を配置する出力ディレクトリ。
        taus: 対象の一致度閾値。

    Returns:
        閾値ごとのサマリ行。
    """
    tag = f"{scope} {level}"

    # 対象クラスタの収集（要素 2 件以上のみ代表を作る）
    clusters: dict[float, list[dict[str, Any]]] = {}
    needed: set[int] = set()
    for tau in taus:
        path = phase1_dir / f"tau{round(tau * 10):02d}" / level / f"{scope}_clusters.jsonl"
        if not path.exists():
            continue
        rows: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                cluster = json.loads(line)
                if cluster["size"] >= 2:
                    rows.append(cluster)
                    needed.update(cluster["members"])
        clusters[tau] = rows
    print(f"[{tag}] クラスタ {sum(len(rows) for rows in clusters.values())} / 必要なレコード {len(needed)}", flush=True)

    # 切り出しの読み込み（区切り記号を除き origin_index 昇順に整える）
    nodes_of: dict[int, list[CutNode]] = {}
    with open(phase0_dir / f"{scope}.json", "rb") as f:
        for record in ijson.items(f, "item"):
            if record["id"] not in needed:
                continue
            kept = [CutNode(node["origin_index"], node["name"], node["value"], tuple(node["parent"])) for node in record["nodes"] if node["name"] not in DELIMITER_NAMES]
            if kept:
                kept.sort(key=lambda node: node.origin_index)
                nodes_of[record["id"]] = kept
    print(f"[{tag}] ノード読み込み完了 {len(nodes_of)}", flush=True)

    summary: list[dict[str, Any]] = []
    for tau in sorted(clusters):
        cell_dir = phase2_dir / f"tau{round(tau * 10):02d}" / level
        cell_dir.mkdir(parents=True, exist_ok=True)

        written = 0
        skipped = 0
        empty = 0
        coverages: list[float] = []
        retentions: list[float] = []
        descendant_edges = 0
        with open(cell_dir / f"{scope}_representatives.jsonl", "w", encoding="utf-8") as f:
            for cluster in clusters[tau]:
                members = [mb_id for mb_id in cluster["members"] if mb_id in nodes_of]
                if len(members) < 2:
                    skipped += 1
                    continue
                result = _representative(members, [nodes_of[mb_id] for mb_id in members], level)
                payload = {"cluster_id": cluster["cluster_id"], "size": len(members), "members": members, "patterns": result["patterns"]}
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
                written += 1
                empty += 1 if result["node_count"] == 0 else 0
                coverages.append(result["coverage"])
                retentions.append(result["retention"])
                descendant_edges += result["descendant_edges"]

        summary.append(
            {
                "scope": scope,
                "level": level,
                "threshold": tau,
                "clusters": len(clusters[tau]),
                "representatives": written,
                "skipped": skipped,
                "empty": empty,
                "descendant_edges": descendant_edges,
                "coverage_full": sum(1 for value in coverages if value == 1.0),
                "coverage_mean": sum(coverages) / len(coverages) if coverages else 0.0,
                "retention_mean": sum(retentions) / len(retentions) if retentions else 0.0,
            }
        )
        print(
            f"[{tag}] tau={tau}: 代表 {written} / 被覆 100% が {summary[-1]['coverage_full']} / 平均被覆 {summary[-1]['coverage_mean']:.3f} / 平均残存率 {summary[-1]['retention_mean']:.3f}",
            flush=True,
        )

    return summary


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数とパスの解決 ---
    parser = argparse.ArgumentParser(description="cluster representatives by anti-unification over scope cutouts")
    parser.add_argument("--levels", nargs="+", default=list(ABSTRACTION_LEVELS), help="抽象度の水準")
    parser.add_argument("--scopes", nargs="+", default=list(SCOPES), help="対象スコープ")
    parser.add_argument("--taus", type=float, nargs="+", default=list(THRESHOLDS), help="一致度閾値")
    parser.add_argument("--workers", type=int, default=6, help="並列ワーカー数（スコープ × 抽象度の組を割り当てる）")
    args = parser.parse_args()

    config = PathConfig()
    phase0_dir = config.outputs / "saner" / "approach" / "phase0"
    phase1_dir = config.outputs / "saner" / "approach" / "phase1"
    phase2_dir = config.outputs / "saner" / "approach" / "phase2"

    missing = [phase0_dir / f"{scope}.json" for scope in args.scopes if not (phase0_dir / f"{scope}.json").exists()]
    if missing:
        raise FileNotFoundError(f"入力ファイルが見つかりません: {missing}")
    if not phase1_dir.exists():
        raise FileNotFoundError(f"phase1 の出力が見つかりません: {phase1_dir}")
    phase2_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: スコープ × 抽象度の組を並列に処理する ---
    jobs = [(scope, level) for scope in args.scopes for level in args.levels]
    print(f"Output: {phase2_dir}")
    print(f"jobs={len(jobs)} workers={args.workers} levels={args.levels} scopes={args.scopes} taus={sorted(args.taus)}\n")

    summary: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_process_cell, scope, level, phase0_dir, phase1_dir, phase2_dir, sorted(args.taus)): (scope, level) for scope, level in jobs}
        for future in as_completed(futures):
            scope, level = futures[future]
            summary.extend(future.result())
            print(f"[DONE] {scope} {level}", flush=True)

    # --- Section 3: サマリの書き出し ---
    summary.sort(key=lambda row: (row["scope"], row["level"], row["threshold"]))
    summary_path = phase2_dir / "representative_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"ignore_names": sorted(DELIMITER_NAMES), "cells": summary}, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"\nWritten: {summary_path}")
