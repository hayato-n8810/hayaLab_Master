r"""実験ランナー: MBDiff.json の base_ast / head_ast に対して低速パターンを検出する。

Usage:
    uv run python experiments/scam/PreAnalysis/run.py \
        --input data/processed/MBDiff.json \
        --output-dir outputs/scam/PreAnalysis \
        --patterns 1,2,3,4,5,6,7,8,9,10

Notes:
    - 2.9 GB の MBDiff.json を ijson でストリーミング読み込みする。
    - パターン定義 JSON の部分木仕様（slow側の特徴のみ）を base_ast（slow 側）に適用し、
      ヒットしたレコードのみ head_ast（fast 側）にも同じ仕様を適用する。
    - base ヒット全件と、base ヒットかつ head 非ヒットの 2 ファイルを出力する。
    - 差分ではなく，base ヒットかつ head 非ヒット（変更箇所に含まれる）とすることで，変更箇所に含まれているかを確認
    - ここでは，「変更パターン」ではなく，「低速パターン」に注目していることに留意
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

_SPEC_PATH = Path(__file__).parent / "patterns" / "slow_patterns.json"

if __name__ == "__main__":
    config = PathConfig()
    parser = argparse.ArgumentParser(description="Slow pattern detection on MBDiff.json")
    parser.add_argument("--input", default=f"{config.processed}/MBDiff.json", help="Input MBDiff.json path")
    parser.add_argument("--output-dir", default=f"{config.outputs}/saner/PreAnalysis", help="Output directory")
    parser.add_argument("--patterns", default="1,2,3,4,5,6,7,8,9,10", help="Comma-separated pattern IDs")
    parser.add_argument("--spec", default=str(_SPEC_PATH), help="Pattern specification JSON path")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    spec_path = Path(args.spec)
    pattern_ids = {int(p.strip()) for p in args.patterns.split(",") if p.strip()}

    # --- 入力検証 ---
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    if not spec_path.exists():
        print(f"[ERROR] Pattern spec not found: {spec_path}", file=sys.stderr)
        sys.exit(1)

    # --- パターン仕様の読み込み ---
    with open(spec_path, encoding="utf-8") as f:
        patterns = [p for p in load_tree_patterns(json.load(f)) if p.pattern_id in pattern_ids]
    print(f"Patterns: {[p.pattern_id for p in patterns]}")
    print(f"Input: {input_path}")
    print(f"Spec: {spec_path}")
    print(f"Output: {output_dir}")

    # --- レコード走査: base 検出 → ヒット時のみ head 検出 ---
    base_rows: list[dict[str, object]] = []
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
            head_nodes: list[ASTNode] | None = None

            for pattern in patterns:
                base_matches = find_tree_matches(base_nodes, base_code, pattern)
                if not base_matches:
                    continue
                if head_nodes is None:
                    head_nodes = [ASTNode(**t) for t in head_ast.get("tree", [])]
                head_matches = find_tree_matches(head_nodes, head_code, pattern)

                base_rows.append(
                    {
                        "mb_id": mb_id,
                        "target_id": pattern.pattern_id,
                        "base_count": len(base_matches),
                        "head_count": len(head_matches),
                        "head_hit": bool(head_matches),
                        "snippet": base_matches[0].snippet,
                        "base_code": base_code,
                        "head_code": head_code,
                    }
                )

    print(f"Processed {count} records, {len(base_rows)} (mb_id, pattern) hits on base_ast.")

    # --- 出力書き出し ---
    output_dir.mkdir(parents=True, exist_ok=True)
    base_only_rows = [row for row in base_rows if not row["head_hit"]]

    for filename, rows in (("base_hits.jsonl", base_rows), ("base_only_hits.jsonl", base_only_rows)):
        path = output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"Written: {path} ({len(rows)} rows)")

    by_pid_base: dict[int, int] = defaultdict(int)
    by_pid_base_only: dict[int, int] = defaultdict(int)
    for row in base_rows:
        by_pid_base[row["target_id"]] += 1
        if not row["head_hit"]:
            by_pid_base_only[row["target_id"]] += 1

    summary_list = [
        {
            "target_id": pattern.pattern_id,
            "key": pattern.key,
            "base_hit_count": by_pid_base.get(pattern.pattern_id, 0),
            "base_only_hit_count": by_pid_base_only.get(pattern.pattern_id, 0),
        }
        for pattern in patterns
    ]
    summary_path = output_dir / "summary.json"
    hayalab.write_json(summary_path, summary_list)
    print(f"Written: {summary_path}")
    for entry in summary_list:
        print(f"  Pattern {entry['target_id']}: base={entry['base_hit_count']}, base_only={entry['base_only_hit_count']}")
