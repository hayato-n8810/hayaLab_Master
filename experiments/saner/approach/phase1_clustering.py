"""Phase 1: phase0 のスコープ別切り出しを bigram Jaccard の complete-linkage でクラスタリングする。

スコープ 3 種 × 抽象度 2 水準の 6 組を並列に処理する。各組が「入力 → 処理 → 出力」を独立に完結させる。

抽象度は alpha1 / alpha2 の 2 水準。データは書き換えず、ラベル射影でのみ value の扱いを変える。

| 条件 | alpha1 のラベル | alpha2 のラベル |
|---|---|---|
| ``value`` がプレースホルダ識別子（``VAR_1`` 等） | ``name`` | ``name`` |
| ``name`` が ``number`` / ``string_fragment`` | ``name:value`` | ``name`` |
| ``regex`` ノードの子孫 | ``name:value`` | ``name`` |
| 上記以外（API 名・演算子・非終端） | ``name:value`` | ``name:value`` |

区切り記号は親ノードの型から一意に定まるため除去する。演算子は親の型から定まらないため残す。

切り出し結果は ``origin_index`` 昇順のノード列としてそのまま扱う。森であっても仮想ルートを
立てず、preorder 走査順の隣接 2 ラベルを bigram とする。

有効トークン数 ``n_t`` で処理を振り分ける。

* ``n_t == 0``  — 除外（クラスタ生成対象外）
* ``n_t == 1``  — トークン完全一致で grouping
* ``n_t >= 2``  — bigram Jaccard の complete-linkage

一致度は候補の絞り込みを行わず、全ペアについて算出する。疎行列積 ``X @ X.T`` は
全ペアの積集合サイズを与え、格納されない成分は「計算していない」のではなく値が 0 である。
Jaccard は ``|A∩B| / (|A| + |B| - |A∩B|)`` として全ペア分を評価する。

クラスタリングは凝集型 complete-linkage そのものを行う。クラスタ間距離を
``D(A, B) = min_{a in A, b in B} sim(a, b)`` と定め、``D`` が最大のクラスタ対から順に併合する。
併合高さは非増加（complete-linkage は逆転を持たない）ため、併合履歴の接頭部分を取ることで
任意の閾値における切断が得られる。同値の場合はクラスタ代表（メンバー最小 index）の昇順で決定的に選ぶ。

``D(A, B) >= tau`` となる併合はすべての交差ペアが ``tau`` 以上であることを要するため、
``tau`` 未満の一致度は切断高さ ``tau`` 以下の併合に関与しない。よって辺の保持は
``--floor``（既定は ``--taus`` の最小値）以上に限ってよい。

出力:
    outputs/saner/approach/phase1/tau{NN}/{level}/{scope}_clusters.jsonl
    outputs/saner/approach/phase1/cluster_summary.json

出力 JSONL の 1 行は ``{"cluster_id", "size", "members", "origin"}``。
``members`` は mb_id 昇順、``origin`` は ``"bigram"`` / ``"unigram"``。
"""

from __future__ import annotations

import argparse
import heapq
import json
import re
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import ijson
import numpy as np
from scipy.sparse import csr_matrix

from hayalab.config import PathConfig

# --- Constants (hyperparameters tunable at the top of the file) ----
# 入力ファイル名（phase0 のスコープ別切り出し）
INPUT_NAMES: tuple[str, ...] = ("sigma_1.json", "sigma_2.json", "sigma_3.json")

# 一致度閾値の水準
THRESHOLDS: tuple[float, ...] = (0.6, 0.7, 0.8, 0.9)

# 抽象度の水準
ABSTRACTION_LEVELS: tuple[str, ...] = ("alpha1", "alpha2")

# n-gram の n
NGRAM_N: int = 2

# 全ペア一致度を算出する際の行ブロック幅
BLOCK_ROWS: int = 1024

# 全ペア一致度の進捗を報告する間隔（ブロック数）
PROGRESS_BLOCKS: int = 8

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


# --- Helpers (only those called many times) ------------------------
def _regex_descendant_indices(nodes: list[dict[str, Any]]) -> frozenset[int]:
    """``regex`` ノードの子孫の ``origin_index`` 集合を返す。

    ``regex`` ノード自身は含めない。判定は切り出し内に存在する ``regex`` ノードに限る。

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
    """ノードの比較用ラベルを返す。

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


def _record_tokens(nodes: list[dict[str, Any]], level: str) -> list[str]:
    """1 レコード分の有効トークン列を返す。

    区切り記号を除き、``origin_index`` 昇順のラベル列にする。

    Args:
        nodes: 切り出し結果の 1 レコード分のノード列。
        level: 抽象度（``"alpha1"`` / ``"alpha2"``）。

    Returns:
        preorder 順のラベル列。
    """
    kept = [node for node in nodes if node["name"] not in DELIMITER_NAMES]
    if not kept:
        return []
    kept.sort(key=lambda node: node["origin_index"])
    regex_descendants = _regex_descendant_indices(kept) if level == "alpha2" else frozenset()
    return [_label(node, level, regex_descendants) for node in kept]


def _find(parent: list[int], node: int) -> int:
    """Union-Find の根を返す（経路圧縮あり）。

    Args:
        parent: 親 index の配列。
        node: 対象 index。

    Returns:
        根の index。
    """
    root = node
    while parent[root] != root:
        root = parent[root]
    while parent[node] != root:
        parent[node], node = root, parent[node]
    return root


def _pairwise_edges(gram_sets: list[frozenset[tuple[str, ...]]], floor: float, label: str) -> list[tuple[float, int, int]]:
    """全ペアの Jaccard を算出し、``floor`` 以上のものを返す。

    語彙を列とする 0/1 行列 ``X`` の積 ``X @ X.T`` が全ペアの積集合サイズを与える。
    行ブロックごとに密行列へ展開するため、積集合が 0 のペアも含めて評価する。

    Args:
        gram_sets: 要素ごとの bigram 集合（要素 index 昇順）。
        floor: 保持する一致度の下限。
        label: 進捗表示の接頭辞。

    Returns:
        ``(一致度, left, right)`` の列。``left < right`` かつ ``(left, right)`` 昇順。
    """
    vocabulary: dict[tuple[str, ...], int] = {}
    rows: list[int] = []
    columns: list[int] = []
    for index, gram_set in enumerate(gram_sets):
        for gram in sorted(gram_set):
            rows.append(index)
            columns.append(vocabulary.setdefault(gram, len(vocabulary)))

    total = len(gram_sets)
    matrix = csr_matrix((np.ones(len(rows), dtype=np.int32), (rows, columns)), shape=(total, len(vocabulary)))
    transposed = matrix.T.tocsr()
    sizes = np.asarray([len(gram_set) for gram_set in gram_sets], dtype=np.int32)
    columns_index = np.arange(total)

    edges: list[tuple[float, int, int]] = []
    starts = range(0, total, BLOCK_ROWS)
    for block, start in enumerate(starts):
        end = min(start + BLOCK_ROWS, total)
        intersection = (matrix[start:end] @ transposed).toarray()
        union = sizes[start:end, None] + sizes[None, :] - intersection
        score = intersection / union
        upper = columns_index[None, :] > np.arange(start, end)[:, None]
        left_local, right = np.nonzero((score >= floor) & upper)
        edges.extend((float(score[row, column]), start + int(row), int(column)) for row, column in zip(left_local, right, strict=True))
        if (block + 1) % PROGRESS_BLOCKS == 0 or end == total:
            print(f"[{label}] 全ペア {end}/{total} 行 / 辺 {len(edges):,}", flush=True)
    return edges


def _agglomerate(total: int, edges: list[tuple[float, int, int]]) -> list[tuple[float, int, int]]:
    """凝集型 complete-linkage の併合履歴を返す。

    クラスタ間距離を ``D(A, B) = min`` 交差一致度と定め、``D`` が最大の併合可能な
    クラスタ対から順に併合する。併合可能とは全交差ペアが辺集合に含まれること
    （完全二部結合）であり、これが崩れた対は以後も回復しないため取り除く。

    Args:
        total: 要素数。
        edges: ``(一致度, left, right)`` の列（``left < right``、重複なし）。

    Returns:
        ``(併合高さ, 残る根, 吸収される根)`` の列（併合順、高さは非増加）。
    """
    parent = list(range(total))
    size = [1] * total
    cross_count: dict[tuple[int, int], int] = {}
    cross_min: dict[tuple[int, int], float] = {}
    adjacency: dict[int, set[int]] = defaultdict(set)

    for score, left, right in edges:
        cross_count[(left, right)] = 1
        cross_min[(left, right)] = score
        adjacency[left].add(right)
        adjacency[right].add(left)

    # 同値は (left, right) 昇順で決定的に選ぶ
    heap = [(-score, left, right) for (left, right), score in cross_min.items()]
    heapq.heapify(heap)

    history: list[tuple[float, int, int]] = []
    while heap:
        negated, left, right = heapq.heappop(heap)
        key = (left, right)
        if parent[left] != left or parent[right] != right or key not in cross_min:
            continue
        if cross_min[key] != -negated:
            continue
        if cross_count[key] != size[left] * size[right]:
            # 欠損は併合を重ねても解消しないため、この対を落とす
            del cross_count[key], cross_min[key]
            adjacency[left].discard(right)
            adjacency[right].discard(left)
            continue

        # 残す根は index の小さい側に固定する
        root, absorbed = (left, right) if left < right else (right, left)
        history.append((-negated, root, absorbed))

        for other in sorted(adjacency[absorbed]):
            if other == root:
                continue
            moved_key = (absorbed, other) if absorbed < other else (other, absorbed)
            moved_count = cross_count.pop(moved_key)
            moved_min = cross_min.pop(moved_key)
            adjacency[other].discard(absorbed)
            merged_key = (root, other) if root < other else (other, root)
            if merged_key in cross_count:
                cross_count[merged_key] += moved_count
                cross_min[merged_key] = min(cross_min[merged_key], moved_min)
            else:
                cross_count[merged_key] = moved_count
                cross_min[merged_key] = moved_min
                adjacency[root].add(other)
                adjacency[other].add(root)
            heapq.heappush(heap, (-cross_min[merged_key], *merged_key))

        adjacency[root].discard(absorbed)
        cross_count.pop(key, None)
        cross_min.pop(key, None)
        adjacency.pop(absorbed, None)
        parent[absorbed] = root
        size[root] += size[absorbed]

    return history


def _cut(total: int, history: list[tuple[float, int, int]], threshold: float) -> list[list[int]]:
    """併合履歴を ``threshold`` の高さで切断し、クラスタを返す。

    併合高さは非増加のため、``threshold`` 以上の併合の接頭部分がその高さの分割に一致する。

    Args:
        total: 要素数。
        history: :func:`_agglomerate` の結果。
        threshold: 切断する高さ（一致度）。

    Returns:
        クラスタごとの要素 index リスト（各クラスタ内は昇順、全体も先頭要素の昇順）。
    """
    parent = list(range(total))
    for height, root, absorbed in history:
        if height < threshold:
            break
        parent[absorbed] = root

    grouped: dict[int, list[int]] = defaultdict(list)
    for index in range(total):
        grouped[_find(parent, index)].append(index)
    return sorted(grouped.values(), key=lambda group: group[0])


def _process_cell(input_path: Path, level: str, taus: list[float], floor: float, output_dir: Path, record_limit: int) -> list[dict[str, Any]]:
    """1 組（スコープ × 抽象度）の読み込み・クラスタリング・書き出しを行う。

    ProcessPoolExecutor のワーカーから呼ばれる。入力は ijson で 1 レコードずつ読み、
    トークン化の時点で捨てるため、ノード列全体をメモリに保持しない。

    Args:
        input_path: スコープ別切り出しの JSON パス。
        level: 抽象度（``"alpha1"`` / ``"alpha2"``）。
        taus: 切断する一致度閾値の列。
        floor: 辺として保持する一致度の下限。
        output_dir: ``tau{NN}/{level}`` を配置する出力ディレクトリ。
        record_limit: 先頭から読むレコード数（0 で全件）。

    Returns:
        閾値ごとのサマリ行。

    Raises:
        RuntimeError: 併合高さが非増加でない場合。
    """
    scope = input_path.stem
    tag = f"{scope} {level}"

    # 入力: 有効トークン数で bigram / unigram / 除外に振り分ける
    bigram_of_id: dict[int, frozenset[tuple[str, ...]]] = {}
    unigram_of_id: dict[int, tuple[str, ...]] = {}
    empty_records = 0
    records = 0
    with open(input_path, "rb") as f:
        for record in ijson.items(f, "item"):
            if record_limit and records >= record_limit:
                break
            records += 1
            tokens = _record_tokens(record["nodes"], level)
            if len(tokens) == 0:
                empty_records += 1
            elif len(tokens) < NGRAM_N:
                unigram_of_id[record["id"]] = tuple(tokens)
            else:
                bigram_of_id[record["id"]] = frozenset(tuple(tokens[i : i + NGRAM_N]) for i in range(len(tokens) - NGRAM_N + 1))
    print(f"[{tag}] レコード {records} / 空 {empty_records} / unigram {len(unigram_of_id)} / bigram {len(bigram_of_id)}", flush=True)

    # 処理: 全ペアの一致度から併合履歴を作る
    member_ids = sorted(bigram_of_id)
    gram_sets = [bigram_of_id[mb_id] for mb_id in member_ids]
    edges = _pairwise_edges(gram_sets, floor, tag)
    history = _agglomerate(len(gram_sets), edges)
    heights = [height for height, _, _ in history]
    if any(earlier < later for earlier, later in zip(heights, heights[1:], strict=False)):
        raise RuntimeError(f"[{tag}] 併合高さが非増加でない（complete-linkage の逆転）")
    print(f"[{tag}] 辺 {len(edges):,} / 併合 {len(history):,}", flush=True)

    # トークン完全一致の grouping（tau に依存しない）
    unigram_buckets: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for mb_id in sorted(unigram_of_id):
        unigram_buckets[unigram_of_id[mb_id]].append(mb_id)
    unigram_groups = sorted(unigram_buckets.values(), key=lambda group: group[0])

    # 出力: tau ごとに切断して書き出す
    summary: list[dict[str, Any]] = []
    for tau in sorted(taus):
        rows = [([member_ids[index] for index in cluster], "bigram") for cluster in _cut(len(gram_sets), history, tau)]
        rows.extend((group, "unigram") for group in unigram_groups)
        rows.sort(key=lambda row: row[0][0])

        cell_dir = output_dir / f"tau{round(tau * 10):02d}" / level
        cell_dir.mkdir(parents=True, exist_ok=True)
        with open(cell_dir / f"{scope}_clusters.jsonl", "w", encoding="utf-8") as f:
            for cluster_id, (group, origin) in enumerate(rows):
                f.write(json.dumps({"cluster_id": cluster_id, "size": len(group), "members": group, "origin": origin}) + "\n")

        summary.append(
            {
                "scope": scope,
                "level": level,
                "threshold": tau,
                "floor": floor,
                "n": NGRAM_N,
                "records": records,
                "empty_records": empty_records,
                "bigram_patterns": len(gram_sets),
                "unigram_patterns": len(unigram_of_id),
                "edges": len(edges),
                "merges": sum(1 for height in heights if height >= tau),
                "clusters": len(rows),
                "singletons": sum(1 for group, _ in rows if len(group) == 1),
                "max_cluster": max((len(group) for group, _ in rows), default=0),
            }
        )
        print(f"[{tag}] tau={tau}: クラスタ {len(rows)} / 単独 {summary[-1]['singletons']} / 最大 {summary[-1]['max_cluster']}", flush=True)

    return summary


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数とパスの解決 ---
    parser = argparse.ArgumentParser(description="true complete-linkage clustering on phase0 scope cutouts")
    parser.add_argument("--levels", nargs="+", default=list(ABSTRACTION_LEVELS), help="抽象度の水準")
    parser.add_argument("--taus", type=float, nargs="+", default=list(THRESHOLDS), help="一致度閾値")
    parser.add_argument("--floor", type=float, default=None, help="辺として保持する一致度の下限（既定は taus の最小値）")
    parser.add_argument("--workers", type=int, default=6, help="並列ワーカー数（スコープ × 抽象度の組を割り当てる）")
    parser.add_argument("--record-limit", type=int, default=0, help="各ファイルの先頭から読むレコード数（0 で全件）")
    args = parser.parse_args()

    config = PathConfig()
    phase0_dir = config.outputs / "saner" / "approach" / "phase0"
    phase1_dir = config.outputs / "saner" / "approach" / "phase1"

    input_paths = [phase0_dir / name for name in INPUT_NAMES]
    missing = [path for path in input_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"入力ファイルが見つかりません: {missing}")
    if not args.taus or min(args.taus) <= 0:
        raise ValueError(f"tau は 0 より大きい値を指定する: {args.taus}")

    floor = args.floor if args.floor is not None else min(args.taus)
    if floor > min(args.taus):
        raise ValueError(f"floor は taus の最小値以下にする: floor={floor} min(taus)={min(args.taus)}")
    phase1_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: スコープ × 抽象度の組を並列に処理する ---
    jobs = [(path, level) for path in input_paths for level in args.levels]
    print(f"Output: {phase1_dir}")
    print(f"jobs={len(jobs)} workers={args.workers} levels={args.levels} taus={sorted(args.taus)} floor={floor} n={NGRAM_N}\n")

    summary: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_process_cell, path, level, sorted(args.taus), floor, phase1_dir, args.record_limit): (path.stem, level) for path, level in jobs}
        for future in as_completed(futures):
            stem, level = futures[future]
            summary.extend(future.result())
            print(f"[DONE] {stem} {level}", flush=True)

    # --- Section 3: サマリの書き出し ---
    summary.sort(key=lambda row: (row["scope"], row["level"], row["threshold"]))
    summary_path = phase1_dir / "cluster_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"\nWritten: {summary_path}")
