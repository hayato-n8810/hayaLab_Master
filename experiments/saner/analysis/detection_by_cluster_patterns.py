"""phase3 のクラスタパターンを ``MBDiff.json`` に当て、検出範囲をクラスタ別に集計する。

``experiments/saner/PreAnalysis/run.py`` と同じ考え方で、パターンを base 側の AST に適用し、
ヒットしたレコードについてのみ head 側にも適用する。base に当たって head に当たらないレコードは
「その変更でパターンが消えた」と読める。

クラスタごとに次を出す。

* ``members``        — クラスタの要素数
* ``member_hits``    — メンバーのうち base 側で自パターンが当たったレコード数
* ``base_hits``      — ``MBDiff.json`` 全体で base 側に当たったレコード数と ID
* ``base_only_hits`` — base に当たって head に当たらなかったレコード数と ID

``member_hits`` は ``base_hit_ids`` とメンバーの積であり、自己再現性を表す。``base_hits`` が
メンバー数を大きく上回るなら、そのパターンはクラスタ外にも広く当たる（汎化が強い）と読める。

name 多重集合による事前足切り
    パターン仕様中の具体的な ``name``（``*`` や選言でないもの）は、対象 AST に同じ ``name`` の
    ノードがその個数以上なければ一致しえない。よって多重集合の包含を満たさないペアは照合せずに
    不一致と確定できる。結果は総当たりと一致する健全な足切りであり、実測で 90.2% を飛ばす。

パターン単位のシャード分割
    セル（スコープ × 抽象度 × 閾値）を固定単位にすると並列度がセル数で頭打ちになる。各セルの
    パターンを連続した塊に分けてジョブとすることで、任意のワーカー数まで分割できる。各パターンは
    ちょうど 1 シャードに属するため、集約はシャード出力の連結で済む（ヒット ID の併合が要らない）。
    ``load_tree_patterns`` が ``pattern_id`` 昇順に並べるため、連結した時点でクラスタ ID 昇順になる。

シャードは ``_shards`` 以下に中間 JSONL を書き、集約時に 1 行ずつ読んで最終 JSON へ流す。
ヒット ID の列は大きくなりうるため、メモリに全行を載せない。

出力:
    outputs/saner/analysis/detection/tau{NN}/{level}/{scope}_evaluation.json
    outputs/saner/analysis/detection/evaluation_summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import ijson

from hayalab.classes.gumtree import ASTNode
from hayalab.config import PathConfig
from hayalab.gumtree import find_tree_matches, load_tree_patterns

# --- Constants (hyperparameters tunable at the top of the file) ----
# 対象スコープ（phase0 の出力ファイル名と対応する）
SCOPES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")

# 抽象度の水準
ABSTRACTION_LEVELS: tuple[str, ...] = ("alpha1", "alpha2")

# 一致度閾値の水準
THRESHOLDS: tuple[float, ...] = (0.6, 0.7, 0.8, 0.9)

# ヒット有無だけを見るため snippet は保持しない
SNIPPET_LIMIT: int = 1

# ワーカー 1 つあたりに割り当てるシャード数（多いほど負荷が揃い、解析の重複が増える）
SHARDS_PER_WORKER: int = 2

# 進捗を報告するレコード間隔
PROGRESS_RECORDS: int = 10000

# シャードの中間出力を置くディレクトリ名
SHARD_DIRNAME: str = "_shards"

# 任意のノードに一致するノード名（足切りの対象外）
WILDCARD_NAME: str = "*"


# --- Helpers (only those called many times) ------------------------
def _required_names(spec: dict[str, Any], required: Counter[str]) -> Counter[str]:
    """パターン仕様が要求する具体的な ``name`` の多重集合を数える。

    ``*`` や選言（リスト指定）は特定の ``name`` を要求しないため数えない。

    Args:
        spec: ノード仕様。
        required: 積み上げ先の Counter。

    Returns:
        ``required`` そのもの。
    """
    name = spec.get("name")
    if isinstance(name, str) and name != WILDCARD_NAME:
        required[name] += 1
    for child in spec.get("children") or []:
        _required_names(child, required)
    return required


def _cell_key(scope: str, level: str, tau: float) -> str:
    """セルを識別する文字列を返す。

    Args:
        scope: スコープ名。
        level: 抽象度。
        tau: 一致度閾値。

    Returns:
        ``tau{NN}_{level}_{scope}`` 形式の文字列。
    """
    return f"tau{round(tau * 10):02d}_{level}_{scope}"


def _merge_shards(shard_paths: list[Path], output_path: Path, header: dict[str, Any]) -> None:
    """シャードの中間 JSONL を 1 本の JSON に連結する。

    シャードはクラスタ ID 昇順の連続した区間なので、順に連結するだけで整列済みになる。
    ヒット ID の列が大きくなりうるため、1 行ずつ読んで書き出す。

    Args:
        shard_paths: 連結するシャードファイル（区間の昇順）。
        output_path: 出力先。
        header: ``clusters`` 以外のトップレベル項目。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out:
        out.write("{\n")
        for key, value in header.items():
            out.write(f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)},\n")
        out.write('  "clusters": [\n')
        first = True
        for shard_path in shard_paths:
            with open(shard_path, encoding="utf-8") as shard:
                for line in shard:
                    out.write(("" if first else ",\n") + "    " + line.rstrip("\n"))
                    first = False
        out.write("\n  ]\n}\n")


# --- Pool workers (ProcessPoolExecutor 経由で参照するためトップレベルに置く) ----
def _process_shard(scope: str, level: str, tau: float, start: int, end: int, shard: int, phase2_dir: Path, phase3_dir: Path, shard_dir: Path, input_path: Path) -> dict[str, Any]:
    """1 シャード分のパターンを ``MBDiff.json`` に当て、中間 JSONL を書き出す。

    Args:
        scope: スコープ名。
        level: 抽象度。
        tau: 一致度閾値。
        start: 担当するパターンの開始位置（pattern_id 昇順の並びにおける index）。
        end: 担当するパターンの終了位置（含まない）。
        shard: シャード番号。
        phase2_dir: phase2 の出力ディレクトリ（メンバー ID の取得に使う）。
        phase3_dir: phase3 の出力ディレクトリ（パターン仕様の取得に使う）。
        shard_dir: 中間出力を置くディレクトリ。
        input_path: ``MBDiff.json`` のパス。

    Returns:
        シャード単位のサマリ行。
    """
    suffix = f"tau{round(tau * 10):02d}"
    tag = f"{scope} {level} {suffix} #{shard}"

    with open(phase3_dir / suffix / level / f"{scope}_patterns.json", encoding="utf-8") as f:
        patterns = load_tree_patterns(json.load(f))[start:end]
    required_of = [_required_names(pattern.root, Counter()) for pattern in patterns]
    members_of = {payload["cluster_id"]: payload["members"] for payload in (json.loads(line) for line in open(phase2_dir / suffix / level / f"{scope}_representatives.jsonl", encoding="utf-8"))}
    print(f"[{tag}] パターン {len(patterns)} 件（{start}-{end}）", flush=True)

    base_hits: list[list[int]] = [[] for _ in patterns]
    base_only_hits: list[list[int]] = [[] for _ in patterns]
    records = 0
    skipped = 0
    with open(input_path, "rb") as f:
        for record in ijson.items(f, "item"):
            records += 1
            diff = record["diff"]
            base, head = diff["base_ast"], diff["head_ast"]
            base_nodes = [ASTNode(**tree_node) for tree_node in base["tree"]]
            base_bag = Counter(node.name for node in base_nodes)
            head_nodes: list[ASTNode] | None = None
            head_bag: Counter[str] = Counter()

            for index, pattern in enumerate(patterns):
                # name 多重集合の包含を満たさなければ照合せずに不一致と確定する
                if any(base_bag[name] < count for name, count in required_of[index].items()):
                    skipped += 1
                    continue
                if not find_tree_matches(base_nodes, base["code"], pattern, snippet_limit=SNIPPET_LIMIT):
                    continue
                base_hits[index].append(record["id"])
                # base に当たったパターンだけ head 側を評価する
                if head_nodes is None:
                    head_nodes = [ASTNode(**tree_node) for tree_node in head["tree"]]
                    head_bag = Counter(node.name for node in head_nodes)
                if any(head_bag[name] < count for name, count in required_of[index].items()):
                    base_only_hits[index].append(record["id"])
                elif not find_tree_matches(head_nodes, head["code"], pattern, snippet_limit=SNIPPET_LIMIT):
                    base_only_hits[index].append(record["id"])
            if records % PROGRESS_RECORDS == 0:
                print(f"[{tag}] {records} レコード", flush=True)

    shard_dir.mkdir(parents=True, exist_ok=True)
    shard_path = shard_dir / f"{_cell_key(scope, level, tau)}_{shard:04d}.jsonl"
    base_total = head_total = 0
    covered = 0
    with open(shard_path, "w", encoding="utf-8") as f:
        for index, pattern in enumerate(patterns):
            members = members_of.get(pattern.pattern_id, [])
            hits = base_hits[index]
            base_total += len(hits)
            head_total += len(base_only_hits[index])
            member_hits = len(set(hits) & set(members))
            covered += 1 if members and member_hits == len(members) else 0
            row = {
                "cluster_id": pattern.pattern_id,
                "members": len(members),
                "member_hits": member_hits,
                "base_hits": len(hits),
                "base_hit_ids": hits,
                "base_only_hits": len(base_only_hits[index]),
                "base_only_hit_ids": base_only_hits[index],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[{tag}] 完了: 足切り {skipped:,} / base ヒット {base_total:,} / base のみ {head_total:,}", flush=True)
    return {
        "scope": scope,
        "level": level,
        "threshold": tau,
        "shard": shard,
        "path": str(shard_path),
        "records": records,
        "patterns": len(patterns),
        # "skipped_pairs": skipped,
        "full_member_coverage": covered,
        "base_hit_total": base_total,
        "base_only_hit_total": head_total,
    }


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数とパスの解決 ---
    parser = argparse.ArgumentParser(description="evaluate cluster patterns against MBDiff.json")
    parser.add_argument("--scopes", nargs="+", default=list(SCOPES), help="対象スコープ")
    parser.add_argument("--levels", nargs="+", default=list(ABSTRACTION_LEVELS), help="抽象度の水準")
    parser.add_argument("--taus", type=float, nargs="+", default=list(THRESHOLDS), help="一致度閾値")
    parser.add_argument("--workers", type=int, default=6, help="並列ワーカー数")
    args = parser.parse_args()

    config = PathConfig()
    input_path = config.processed / "MBDiff.json"
    phase2_dir = config.outputs / "saner" / "approach" / "phase2"
    phase3_dir = config.outputs / "saner" / "approach" / "phase3"
    output_dir = config.outputs / "saner" / "analysis" / "detection"
    shard_dir = output_dir / SHARD_DIRNAME

    for path in (input_path, phase2_dir, phase3_dir):
        if not path.exists():
            raise FileNotFoundError(f"入力が見つかりません: {path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: パターンファイルを走査して均等なシャードを組む ---
    counts: dict[tuple[str, str, float], int] = {}
    for tau in sorted(args.taus):
        for level in args.levels:
            for scope in args.scopes:
                pattern_path = phase3_dir / f"tau{round(tau * 10):02d}" / level / f"{scope}_patterns.json"
                if not pattern_path.exists():
                    print(f"[WARN] パターンファイルが無い: {pattern_path}")
                    continue
                with open(pattern_path, encoding="utf-8") as f:
                    counts[(scope, level, tau)] = len(json.load(f)["patterns"])
    cells = [cell for cell in ((scope, level, tau) for tau in sorted(args.taus) for level in args.levels for scope in args.scopes) if counts.get(cell)]
    if not cells:
        raise SystemExit("対象セルがありません")

    total_patterns = sum(counts[cell] for cell in cells)
    chunk = max(1, math.ceil(total_patterns / max(1, args.workers * SHARDS_PER_WORKER)))
    jobs: list[tuple[str, str, float, int, int, int]] = []
    for scope, level, tau in cells:
        size = counts[(scope, level, tau)]
        jobs.extend((scope, level, tau, start, min(start + chunk, size), shard) for shard, start in enumerate(range(0, size, chunk)))
    # 重い順に投入して末尾の待ち時間を減らす
    jobs.sort(key=lambda job: job[3] - job[4])

    print(f"Input:  {input_path}")
    print(f"Output: {output_dir}")
    print(f"cells={len(cells)} patterns={total_patterns:,} chunk={chunk} jobs={len(jobs)} workers={args.workers}\n")

    # --- Section 3: シャード単位で並列に評価する ---
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_process_shard, scope, level, tau, start, end, shard, phase2_dir, phase3_dir, shard_dir, input_path) for scope, level, tau, start, end, shard in jobs]
        for future in as_completed(futures):
            results.append(future.result())

    # --- Section 4: セルごとにシャードを連結する ---
    summary: list[dict[str, Any]] = []
    for scope, level, tau in cells:
        parts = sorted((row for row in results if (row["scope"], row["level"], row["threshold"]) == (scope, level, tau)), key=lambda row: row["shard"])
        if not parts:
            continue
        suffix = f"tau{round(tau * 10):02d}"
        header = {"scope": scope, "level": level, "threshold": tau, "records": max(row["records"] for row in parts)}
        _merge_shards([Path(row["path"]) for row in parts], output_dir / suffix / level / f"{scope}_evaluation.json", header)
        summary.append(
            {
                **header,
                "shards": len(parts),
                "patterns": sum(row["patterns"] for row in parts),
                # "skipped_pairs": sum(row["skipped_pairs"] for row in parts),
                "full_member_coverage": sum(row["full_member_coverage"] for row in parts),
                "base_hit_total": sum(row["base_hit_total"] for row in parts),
                "base_only_hit_total": sum(row["base_only_hit_total"] for row in parts),
            }
        )
        print(f"[MERGE] {scope} {level} {suffix}: シャード {len(parts)} → パターン {summary[-1]['patterns']}")

    shutil.rmtree(shard_dir, ignore_errors=True)

    # --- Section 5: サマリの書き出し ---
    summary.sort(key=lambda row: (row["scope"], row["level"], row["threshold"]))
    summary_path = output_dir / "evaluation_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"\nWritten: {summary_path}")
