r"""実験ランナー: MBDiff.json に対して低速パターン検出（Stage A/B）を実行する。

Usage:
    uv run python -m experiments.scam.PreAnalysis.run \\
        --input data/processed/MBDiff.json \\
        --output-dir outputs/scam/PreAnalysis \\
        --patterns 1,2,3,4,5,6,7,8,9,10

Notes:
    - 2.9 GB の MBDiff.json を ijson でストリーミング読み込みする。
    - Stage A: matcher を base_ast.tree 全件に適用し、 is_base_covered で
      base_action 配下外のマッチを除外。
    - Stage B: apply_diff_link で fast 側に該当書き換えがあるかを判定し
      diff_linked フラグを立てる。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

import ijson
from tqdm import tqdm

import hayalab
from hayalab.classes.gumtree import ASTNode, GumAction
from hayalab.config import PathConfig
from hayalab.scam.diff_link import apply_diff_link, is_base_covered
from hayalab.scam.match.base import PatternMatch
from hayalab.scam.match.p01_for_in_has_own import ForInHasOwnMatcher
from hayalab.scam.match.p02_substr_single_char import SubstrSingleCharMatcher
from hayalab.scam.match.p03_string_cast import StringCastMatcher
from hayalab.scam.match.p04_jquery_html_empty import JQueryHtmlEmptyMatcher
from hayalab.scam.match.p05_substr_prefix_cmp import SubstrPrefixCmpMatcher
from hayalab.scam.match.p06_split_join_chain import SplitJoinChainMatcher
from hayalab.scam.match.p07_to_string_call import ToStringCallMatcher
from hayalab.scam.match.p08_modulo_even_odd import ModuloEvenOddMatcher
from hayalab.scam.match.p09_higher_order_array import HigherOrderArrayMatcher
from hayalab.scam.match.p10_slice_join_single import SliceJoinSingleMatcher

_ALL_MATCHERS = [
    ForInHasOwnMatcher(),
    SubstrSingleCharMatcher(),
    StringCastMatcher(),
    JQueryHtmlEmptyMatcher(),
    SubstrPrefixCmpMatcher(),
    SplitJoinChainMatcher(),
    ToStringCallMatcher(),
    ModuloEvenOddMatcher(),
    HigherOrderArrayMatcher(),
    SliceJoinSingleMatcher(),
]


def _parse_actions(actions: list[dict[str, Any]]) -> list[GumAction]:
    """Actions の dict リストを GumAction リストに変換する（スキーマ非互換は無視）。

    base_actions と head_actions の 2 箇所から呼ばれる共通変換のため関数化。
    """
    result: list[GumAction] = []
    for a in actions:
        try:
            result.append(GumAction(**a))
        except Exception:  # noqa: BLE001 -- スキーマ非互換は意図的にスキップ
            pass
    return result


if __name__ == "__main__":
    config = PathConfig()
    parser = argparse.ArgumentParser(description="Slow pattern detection on MBDiff.json")
    parser.add_argument("--input", default=f"{config.processed}/MBDiff.json", help="Input MBDiff.json path")
    parser.add_argument("--output-dir", default=f"{config.outputs}/scam/PreAnalysis", help="Output directory")
    parser.add_argument("--patterns", default="1,2,3,4,5,6,7,8,9,10", help="Comma-separated pattern IDs")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    pattern_ids = [int(p.strip()) for p in args.patterns.split(",") if p.strip()]

    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    id_set = set(pattern_ids)
    matchers = [m for m in _ALL_MATCHERS if m.pattern_id in id_set]
    print(f"Patterns: {[m.pattern_id for m in matchers]}")
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")

    all_matches: list[PatternMatch] = []
    hits_by_mb: dict[int, tuple[str, str]] = {}
    count = 0

    with open(input_path, "rb") as f:
        for record in tqdm(ijson.items(f, "item"), desc="Processing", unit="rec"):
            count += 1
            mb_id = record.get("id", 0)
            diff = record.get("diff", {})
            base_ast = diff.get("base_ast", {})
            base_code = base_ast.get("code", "")
            head_ast = diff.get("head_ast", {})
            head_code = head_ast.get("code", "")

            nodes = [ASTNode(**t) for t in base_ast.get("tree", [])]

            # Stage A: BEFORE 構造を matcher で検出
            stage_a: list[PatternMatch] = []
            for matcher in matchers:
                for pm in matcher.find(nodes, base_code, mb_id=mb_id):
                    stage_a.append(pm)
            if not stage_a:
                continue

            # base_covered フィルタ（base_action 配下外のマッチを除外）
            base_actions = _parse_actions(diff.get("base_actions", []))
            covered = [pm for pm in stage_a if is_base_covered(pm, base_actions, base_nodes=nodes)]
            if not covered:
                continue

            # Stage B: diff 連動判定
            head_actions = _parse_actions(diff.get("head_actions", []))
            head_nodes = [ASTNode(**t) for t in head_ast.get("tree", [])]
            matches_raw = diff.get("matches", [])
            linked = [apply_diff_link(pm, base_actions, head_actions, matches_raw, head_nodes, base_nodes=nodes) for pm in covered]

            # (mb_id, pattern_id) 重複を 1 件に集約
            #   - diff_linked: いずれか True なら True
            #   - diff_reason: 最初に見つかった non-null
            #   - 代表メンバー: diff_linked=True > begin 小
            groups: dict[tuple[int, int], list[PatternMatch]] = defaultdict(list)
            for pm in linked:
                groups[(pm.mb_id, pm.pattern_id)].append(pm)

            record_matches: list[PatternMatch] = []
            for group in groups.values():
                any_linked = any(m.diff_linked for m in group)
                any_reason = next((m.diff_reason for m in group if m.diff_reason is not None), None)
                rep = max(
                    group,
                    key=lambda pm: (1 if pm.diff_linked else 0, -pm.begin),
                )
                record_matches.append(replace(rep, diff_linked=any_linked, diff_reason=any_reason))

            if record_matches:
                hits_by_mb[mb_id] = (base_code, head_code)
                all_matches.extend(record_matches)

    print(f"Processed {count} records, found {len(all_matches)} matches total.")

    # 出力書き出し: matches.jsonl, summary.json, pattern_{1..10}/diff_linked.jsonl + no_diff_linked.jsonl
    output_dir.mkdir(parents=True, exist_ok=True)

    matches_path = output_dir / "matches.jsonl"
    with open(matches_path, "w", encoding="utf-8") as f:
        for pm in all_matches:
            row = {"mb_id": pm.mb_id, "target_id": pm.pattern_id, "diff_linked": pm.diff_linked}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Written: {matches_path} ({len(all_matches)} matches)")

    by_pid: dict[int, list[PatternMatch]] = defaultdict(list)
    for pm in all_matches:
        by_pid[pm.pattern_id].append(pm)

    summary_list = []
    for pid in range(1, 11):
        pid_matches = by_pid.get(pid, [])
        summary_list.append(
            {
                "target_id": pid,
                "total_mb_ids": len(pid_matches),
                "diff_linked_count": sum(1 for m in pid_matches if m.diff_linked),
                "no_diff_linked_count": sum(1 for m in pid_matches if not m.diff_linked),
            }
        )
    summary_path = output_dir / "summary.json"
    hayalab.write_json(summary_path, summary_list)
    print(f"Written: {summary_path}")

    for pid in range(1, 11):
        pattern_dir = output_dir / f"pattern_{pid}"
        pattern_dir.mkdir(parents=True, exist_ok=True)
        pid_matches = by_pid.get(pid, [])
        linked_matches = [m for m in pid_matches if m.diff_linked]
        unlinked_matches = [m for m in pid_matches if not m.diff_linked]
        for label, bucket in (("diff_linked", linked_matches), ("no_diff_linked", unlinked_matches)):
            path = pattern_dir / f"{label}.jsonl"
            with open(path, "w", encoding="utf-8") as f:
                for pm in bucket:
                    base_code, head_code = hits_by_mb.get(pm.mb_id, ("", ""))
                    row = {
                        "mb_id": pm.mb_id,
                        "target_id": pm.pattern_id,
                        "base_code": base_code,
                        "head_code": head_code,
                    }
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  Pattern {pid}: {len(pid_matches)} matches, {len(linked_matches)} diff_linked")
