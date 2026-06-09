r"""実験ランナー: MBDiff.json に対して低速パターン検出（Stage A/B）を実行する。

Usage:
    uv run python -m experiments.scam.RQ1.run \\
        --input data/processed/MBDiff.json \\
        --output-dir outputs/scam/RQ1 \\
        --patterns 1,2,3,4,5,6,7,8,9,10

    # サンプルドライラン（先頭 N 件）
    uv run python -m experiments.scam.RQ1.run \\
        --input data/processed/MBDiff.json \\
        --output-dir outputs/scam/RQ1 \\
        --limit 500

Notes:
    - 2.9 GB の MBDiff.json を ijson でストリーミング読み込みする。
    - Stage A: slow側の特徴を少なくとも差分に含んでいるものを選択
        base_ast.tree 全件に matcher を適用し、is_base_covered で base_action 配下外のマッチを除外
    - Stage B: fast側の特徴を含んでいるものをにフラグを立てる
        base_actions / matches を参照して diff_linked を判定。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import ijson
from tqdm import tqdm

# ライブラリの import
import hayalab
from hayalab.classes.gumtree import ASTNode, GumAction
from hayalab.config import PathConfig

from .diff_link import apply_diff_link, is_base_covered
from .slow_patterns.base import PatternMatch
from .slow_patterns.p01_for_in_has_own import ForInHasOwnMatcher
from .slow_patterns.p02_substr_single_char import SubstrSingleCharMatcher
from .slow_patterns.p03_string_cast import StringCastMatcher
from .slow_patterns.p04_jquery_html_empty import JQueryHtmlEmptyMatcher
from .slow_patterns.p05_substr_prefix_cmp import SubstrPrefixCmpMatcher
from .slow_patterns.p06_split_join_chain import SplitJoinChainMatcher
from .slow_patterns.p07_to_string_call import ToStringCallMatcher
from .slow_patterns.p08_modulo_even_odd import ModuloEvenOddMatcher
from .slow_patterns.p09_higher_order_array import HigherOrderArrayMatcher
from .slow_patterns.p10_slice_join_single import SliceJoinSingleMatcher

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


def _get_matchers(pattern_ids: list[int]) -> list:
    """指定した pattern_id の matcher を返す。

    Args:
        pattern_ids: 処理対象のパターン番号リスト。

    Returns:
        matcher のリスト。
    """
    id_set = set(pattern_ids)
    return [m for m in _ALL_MATCHERS if m.pattern_id in id_set]


def _iter_records(input_path: Path) -> Any:
    """Ijson でストリーミング読み込みを行う。

    Args:
        input_path: 入力 JSON のパス。

    Yields:
        各レコードの dict。
    """
    with open(input_path, "rb") as f:
        items = ijson.items(f, "item")
        for record in items:
            yield record


def _parse_actions(actions: list[dict[str, Any]]) -> list[GumAction]:
    """Actions リストを GumAction リストに変換する。

    Args:
        actions: GumDiff.base_actions の生 dict リスト。

    Returns:
        GumAction のリスト。
    """
    result = []
    for a in actions:
        try:
            result.append(GumAction(**a))
        except Exception:
            pass  # スキーマ非互換はスキップ
    return result


_CONFIDENCE_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1}


def _dedupe_per_record(matches: list[PatternMatch]) -> list[PatternMatch]:
    """1 レコード内で (mb_id, pattern_id) 重複を 1 件に集約する。

    集約ルール:
        - diff_linked: 同一 (mb_id, pattern_id) でいずれかが True なら True
        - diff_reason: 同一 (mb_id, pattern_id) で最初に見つかった non-null の値
        - その他の代表フィールド（confidence, snippet 等）は以下の優先順位で 1 件を選ぶ:
            1. diff_linked=True を優先
            2. confidence: high > medium > low
            3. 同条件なら begin が小さい（ソース順で早い）方を優先

    Args:
        matches: 同一 mb_id 内の PatternMatch リスト。

    Returns:
        (mb_id, pattern_id) ごとに 1 件に集約した PatternMatch リスト。
    """
    from dataclasses import replace

    def _key(pm: PatternMatch) -> tuple[int, int, int]:
        return (1 if pm.diff_linked else 0, _CONFIDENCE_RANK.get(pm.confidence, 0), -pm.begin)

    groups: dict[tuple[int, int], list[PatternMatch]] = defaultdict(list)
    for pm in matches:
        groups[(pm.mb_id, pm.pattern_id)].append(pm)

    out: list[PatternMatch] = []
    for group in groups.values():
        any_linked = any(m.diff_linked for m in group)
        any_reason = next((m.diff_reason for m in group if m.diff_reason is not None), None)
        rep = max(group, key=_key)
        out.append(replace(rep, diff_linked=any_linked, diff_reason=any_reason))
    return out


def process_record(
    record: dict[str, Any],
    matchers: list,
) -> tuple[list[PatternMatch], str, str]:
    """1 件の MBDiff レコードに対して Stage A/B を実行する。

    Args:
        record: MBDiff.json の 1 レコード。
        matchers: 適用する matcher リスト。

    Returns:
        (PatternMatch のリスト, base_code, head_code) のタプル。
        マッチが 0 件の場合は空リストと空文字列を返す。
    """
    mb_id = record.get("id", 0)
    diff = record.get("diff", {})

    base_ast = diff.get("base_ast", {})
    base_code = base_ast.get("code", "")
    tree_raw = base_ast.get("tree", [])

    # Tree リストを ASTNode リストに変換
    nodes = [ASTNode(**tree) for tree in tree_raw]

    head_ast = diff.get("head_ast", {})
    head_code = head_ast.get("code", "")

    results: list[PatternMatch] = []

    # Stage A: BEFORE-only 検出
    for matcher in matchers:
        for pm in matcher.find(nodes, base_code, mb_id=mb_id):
            results.append(pm)

    if not results:
        return [], base_code, head_code

    # Stage A 後: base_covered フィルタ（--no-stage-b でも適用）
    # base_nodes を渡すことで B2 の subtree 包含判定が正しく行われる
    base_actions = _parse_actions(diff.get("base_actions", []))
    results = [pm for pm in results if is_base_covered(pm, base_actions, base_nodes=nodes)]

    if not results:
        return [], base_code, head_code

    # Stage B: diff 連動フィルタ
    head_actions = _parse_actions(diff.get("head_actions", []))
    matches_raw = diff.get("matches", [])
    head_tree_raw = head_ast.get("tree", [])
    # Tree リストを ASTNode リストに変換
    head_nodes = [ASTNode(**head_tree) for head_tree in head_tree_raw]
    matches = [(b, h) for b, h in matches_raw]

    updated = []
    for pm in results:
        updated.append(apply_diff_link(pm, base_actions, head_actions, matches, head_nodes, base_nodes=nodes))
    return _dedupe_per_record(updated), base_code, head_code


def write_outputs(
    output_dir: Path,
    all_matches: list[PatternMatch],
    hits_by_mb: dict[int, tuple[str, str]],
) -> None:
    """結果を output_dir に書き出す。

    出力ファイル:
        - matches.jsonl: 1行 = {"mb_id", "target_id", "diff_linked"}
        - summary.json: 配列形式、各要素 {"target_id", "total_mb_ids", "diff_linked_count", "no_diff_linked_count"}
        - pattern_{1..10}/diff_linked.jsonl: 1行 = {"mb_id", "target_id", "base_code", "head_code"}
        - pattern_{1..10}/no_diff_linked.jsonl: 同上

    Args:
        output_dir: 出力ディレクトリ。
        all_matches: 全 PatternMatch リスト。
        hits_by_mb: mb_id をキーに (base_code, head_code) を値とする dict。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # matches.jsonl: {"mb_id", "target_id", "diff_linked"} のみ
    matches_path = output_dir / "matches.jsonl"
    with open(matches_path, "w", encoding="utf-8") as f:
        for pm in all_matches:
            row = {"mb_id": pm.mb_id, "target_id": pm.pattern_id, "diff_linked": pm.diff_linked}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Written: {matches_path} ({len(all_matches)} matches)")

    # summary.json: 配列形式、target_id 順
    by_pid: dict[int, list[PatternMatch]] = defaultdict(list)
    for pm in all_matches:
        by_pid[pm.pattern_id].append(pm)

    summary_list = []
    for pid in range(1, 11):
        pid_matches = by_pid.get(pid, [])
        diff_linked_count = sum(1 for m in pid_matches if m.diff_linked)
        no_diff_linked_count = sum(1 for m in pid_matches if not m.diff_linked)
        summary_list.append(
            {
                "target_id": pid,
                "total_mb_ids": len(pid_matches),
                "diff_linked_count": diff_linked_count,
                "no_diff_linked_count": no_diff_linked_count,
            }
        )

    summary_path = output_dir / "summary.json"
    hayalab.write_json(summary_path, summary_list)
    print(f"Written: {summary_path}")

    # pattern_{1..10}/ に diff_linked.jsonl / no_diff_linked.jsonl を常に生成
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


# 実行ポイント
if __name__ == "__main__":
    # TODO: experimentsで収めているため実行は”uv run python -m experiments.scam.RQ1.run”
    # 調整次第，hayalabへ移住

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

    matchers = _get_matchers(pattern_ids)
    print(f"Patterns: {[m.pattern_id for m in matchers]}")
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")

    all_matches: list[PatternMatch] = []
    hits_by_mb: dict[int, tuple[str, str]] = {}
    count = 0

    for record in tqdm(_iter_records(input_path), desc="Processing", unit="rec"):
        matches, base_code, head_code = process_record(record, matchers)
        if matches:
            mb_id = record.get("id", 0)
            hits_by_mb[mb_id] = (base_code, head_code)
            all_matches.extend(matches)
        count += 1

    print(f"Processed {count} records, found {len(all_matches)} matches total.")
    write_outputs(output_dir, all_matches, hits_by_mb)
