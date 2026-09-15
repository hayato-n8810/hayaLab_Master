r"""実験ランナー: MBDiff.json の base_ast / head_ast に対して低速パターンと高速パターンを検出する。

Usage:
    uv run python experiments/scam/PreAnalysis/run.py \
        --input data/processed/MBDiff.json \
        --output-dir outputs/scam/PreAnalysis \
        --patterns 1,2,3,4,5,6,7,8,9,10

Notes:
    - 2.9 GB の MBDiff.json を ijson でストリーミング読み込みする。
    - 低速パターン定義（slow側の特徴のみ）を base_ast（slow 側）に適用し、
      ヒットしたレコードのみ head_ast（fast 側）にも同じ仕様を適用する。
    - 高速パターン定義（fast側の特徴のみ）を head_ast に適用し、
      ヒットしたレコードのみ base_ast にも同じ仕様を適用する。
    - 低速パターンと高速パターンは同一の ID で 1 対 1 に対応させて扱う。
    - 出力は 5 ファイル: base ヒット全件 / base のみヒット / head ヒット全件 / head のみヒット /
      base のみ低速ヒットかつ head のみ高速ヒット（最適化の適用と解釈できるペア）。
    - 差分ではなく，各 AST 側でのヒット有無とすることで，変更箇所に含まれているかを確認
    - ここでは，「変更パターン」ではなく，「低速パターン」「高速パターン」に注目していることに留意
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import ijson
from tqdm import tqdm

import hayalab
from hayalab.classes.gumtree import ASTNode
from hayalab.config import PathConfig
from hayalab.gumtree.tree_pattern import find_tree_matches, load_tree_patterns

_SLOW_SPEC_PATH = Path(__file__).parent / "patterns" / "slow_patterns.json"
_FAST_SPEC_PATH = Path(__file__).parent / "patterns" / "fast_patterns.json"

if __name__ == "__main__":
    config = PathConfig()
    parser = argparse.ArgumentParser(description="Slow/fast pattern detection on MBDiff.json")
    parser.add_argument("--input", default=f"{config.processed}/MBDiff.json", help="Input MBDiff.json path")
    parser.add_argument("--output-dir", default=f"{config.outputs}/saner/PreAnalysis", help="Output directory")
    parser.add_argument("--patterns", default="1,2,3,4,5,6,7,8,9,10", help="Comma-separated pattern IDs")
    parser.add_argument("--spec", default=str(_SLOW_SPEC_PATH), help="Slow pattern specification JSON path")
    parser.add_argument("--fast-spec", default=str(_FAST_SPEC_PATH), help="Fast pattern specification JSON path")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    spec_path = Path(args.spec)
    fast_spec_path = Path(args.fast_spec)
    pattern_ids = {int(p.strip()) for p in args.patterns.split(",") if p.strip()}

    # --- 入力検証 ---
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not spec_path.exists():
        print(f"[ERROR] Pattern spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)
    if not fast_spec_path.exists():
        print(f"[ERROR] Fast pattern spec not found: {fast_spec_path}", file=sys.stderr)
        sys.exit(1)

    # --- パターン仕様の読み込み（同一 ID で slow/fast を対応付ける） ---
    with open(spec_path, encoding="utf-8") as f:
        slow_by_id = {p.pattern_id: p for p in load_tree_patterns(json.load(f)) if p.pattern_id in pattern_ids}
    with open(fast_spec_path, encoding="utf-8") as f:
        fast_by_id = {p.pattern_id: p for p in load_tree_patterns(json.load(f)) if p.pattern_id in pattern_ids}

    paired_ids = sorted(set(slow_by_id) & set(fast_by_id))
    unpaired_ids = sorted(set(slow_by_id) ^ set(fast_by_id))
    if unpaired_ids:
        print(f"[WARN] Unpaired pattern IDs (skipped): {unpaired_ids}", file=sys.stderr)
    if not paired_ids:
        print("[ERROR] No pattern ID is defined in both specs.", file=sys.stderr)
        sys.exit(1)

    print(f"Patterns: {paired_ids}")
    print(f"Input: {input_path}")
    print(f"Spec(slow): {spec_path}")
    print(f"Spec(fast): {fast_spec_path}")
    print(f"Output: {output_dir}")

    # --- レコード走査: slow は base 起点，fast は head 起点で検出 ---
    base_rows: list[dict[str, object]] = []
    head_rows: list[dict[str, object]] = []
    transition_rows: list[dict[str, object]] = []
    count = 0

    with open(input_path, "rb") as f:
        for record in tqdm(ijson.items(f, "item"), desc="Processing", unit="rec"):
            count += 1
            mb_id = record.get("id", 0)
            diff = record.get("diff", {})
            base_ast = diff.get("base_ast", {})
            head_ast = diff.get("head_ast", {})
            base_code = base_ast.get("code", "")
            head_code = head_ast.get("code", "")

            base_nodes = [ASTNode(**t) for t in base_ast.get("tree", [])]
            head_nodes = [ASTNode(**t) for t in head_ast.get("tree", [])]

            for pattern_id in paired_ids:
                slow_pattern = slow_by_id[pattern_id]
                fast_pattern = fast_by_id[pattern_id]

                slow_base = find_tree_matches(base_nodes, base_code, slow_pattern)
                fast_head = find_tree_matches(head_nodes, head_code, fast_pattern)
                # 起点側にヒットした場合のみ，対向側を評価する
                slow_head = find_tree_matches(head_nodes, head_code, slow_pattern) if slow_base else []
                fast_base = find_tree_matches(base_nodes, base_code, fast_pattern) if fast_head else []

                if slow_base:
                    base_rows.append(
                        {
                            "mb_id": mb_id,
                            "target_id": pattern_id,
                            "base_count": len(slow_base),
                            "head_count": len(slow_head),
                            "head_hit": bool(slow_head),
                            "snippet": slow_base[0].snippet,
                            "base_code": base_code,
                            "head_code": head_code,
                        }
                    )

                if fast_head:
                    head_rows.append(
                        {
                            "mb_id": mb_id,
                            "target_id": pattern_id,
                            "head_count": len(fast_head),
                            "base_count": len(fast_base),
                            "base_hit": bool(fast_base),
                            "snippet": fast_head[0].snippet,
                            "base_code": base_code,
                            "head_code": head_code,
                        }
                    )

                # slow が base のみ，fast が head のみにヒットするペア
                if slow_base and not slow_head and fast_head and not fast_base:
                    transition_rows.append(
                        {
                            "mb_id": mb_id,
                            "target_id": pattern_id,
                            "slow_base_count": len(slow_base),
                            "fast_head_count": len(fast_head),
                            "slow_snippet": slow_base[0].snippet,
                            "fast_snippet": fast_head[0].snippet,
                            "base_code": base_code,
                            "head_code": head_code,
                        }
                    )

    print(f"Processed {count} records.")
    print(f"  slow: {len(base_rows)} (mb_id, pattern) hits on base_ast.")
    print(f"  fast: {len(head_rows)} (mb_id, pattern) hits on head_ast.")
    print(f"  transition: {len(transition_rows)} (mb_id, pattern) pairs.")

    # --- 出力書き出し ---
    output_dir.mkdir(parents=True, exist_ok=True)
    base_only_rows = [row for row in base_rows if not row["head_hit"]]
    head_only_rows = [row for row in head_rows if not row["base_hit"]]

    for filename, rows in (
        ("base_hits.jsonl", base_rows),
        ("base_only_hits.jsonl", base_only_rows),
        ("head_hits.jsonl", head_rows),
        ("head_only_hits.jsonl", head_only_rows),
        ("change_hits.jsonl", transition_rows),
    ):
        path = output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Written: {path} ({len(rows)} rows)")

    by_pid_base: dict[int, int] = defaultdict(int)
    by_pid_base_only: dict[int, int] = defaultdict(int)
    by_pid_head: dict[int, int] = defaultdict(int)
    by_pid_head_only: dict[int, int] = defaultdict(int)
    by_pid_transition: dict[int, int] = defaultdict(int)
    transition_ids: dict[int, set[object]] = defaultdict(set)
    for row in base_rows:
        by_pid_base[row["target_id"]] += 1
        if not row["head_hit"]:
            by_pid_base_only[row["target_id"]] += 1
    for row in head_rows:
        by_pid_head[row["target_id"]] += 1
        if not row["base_hit"]:
            by_pid_head_only[row["target_id"]] += 1
    for row in transition_rows:
        by_pid_transition[row["target_id"]] += 1
        transition_ids[row["target_id"]].add(row["mb_id"])

    summary_list = [
        {
            "target_id": pattern_id,
            "key": slow_by_id[pattern_id].key,
            "fast_key": fast_by_id[pattern_id].key,
            "base_hit_count": by_pid_base.get(pattern_id, 0),
            "base_only_hit_count": by_pid_base_only.get(pattern_id, 0),
            "head_hit_count": by_pid_head.get(pattern_id, 0),
            "head_only_hit_count": by_pid_head_only.get(pattern_id, 0),
            "transition_count": by_pid_transition.get(pattern_id, 0),
            "transition_mb_ids": sorted(transition_ids.get(pattern_id, set())),
        }
        for pattern_id in paired_ids
    ]
    summary_path = output_dir / "summary.json"
    hayalab.write_json(summary_path, summary_list)
    print(f"Written: {summary_path}")
    for entry in summary_list:
        print(
            f"  Pattern {entry['target_id']}: base={entry['base_hit_count']}, base_only={entry['base_only_hit_count']}, "
            f"head={entry['head_hit_count']}, head_only={entry['head_only_hit_count']}, change={entry['transition_count']}"
        )
        if entry["transition_mb_ids"]:
            print(f"      transition mb_ids: {entry['transition_mb_ids']}")
