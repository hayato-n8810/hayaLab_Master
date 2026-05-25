"""実験ランナー: MBDiff.json に対して低速パターン検出（Stage A/B）を実行する。

Usage:
    uv run python experiments/tmp/slow_pattern_detect/run.py \\
        --input data/processed/MBDiff.json \\
        --output-dir outputs/tmp/slow_patterns \\
        --patterns 1,2,3,4,5,6,7,8,9,10 \\
        --limit 0

    # サンプルドライラン（先頭 N 件）
    uv run python experiments/tmp/slow_pattern_detect/run.py \\
        --input data/processed/_sample.json \\
        --output-dir outputs/tmp/slow_patterns_sample \\
        --limit 100

Notes:
    - 2.9 GB の MBDiff.json を ijson でストリーミング読み込みする。
      ijson が未インストールの場合は json モジュールで全件読み込みにフォールバックする。
    - Stage A: base_ast.tree 全件に matcher を適用。
    - Stage B: base_actions / matches を参照して diff_linked を判定。
    - 境界規約: hayalab ライブラリに I/O・パス決定を含めない。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from tqdm import tqdm

# ライブラリの import
from hayalab.classes.gumtree import ASTNode, GumAction
from hayalab.tmp.diff_link import apply_diff_link
from hayalab.tmp.slow_patterns.base import PatternMatch
from hayalab.tmp.slow_patterns.p01_for_in_has_own import ForInHasOwnMatcher
from hayalab.tmp.slow_patterns.p02_substr_single_char import SubstrSingleCharMatcher
from hayalab.tmp.slow_patterns.p03_string_cast import StringCastMatcher
from hayalab.tmp.slow_patterns.p04_jquery_html_empty import JQueryHtmlEmptyMatcher
from hayalab.tmp.slow_patterns.p05_substr_prefix_cmp import SubstrPrefixCmpMatcher
from hayalab.tmp.slow_patterns.p06_split_join_chain import SplitJoinChainMatcher
from hayalab.tmp.slow_patterns.p07_to_string_call import ToStringCallMatcher
from hayalab.tmp.slow_patterns.p08_modulo_even_odd import ModuloEvenOddMatcher
from hayalab.tmp.slow_patterns.p09_higher_order_array import HigherOrderArrayMatcher
from hayalab.tmp.slow_patterns.p10_slice_join_single import SliceJoinSingleMatcher

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


def _iter_records_json(input_path: Path, limit: int):
    """通常の json モジュールで MBDiff.json を読み込む（メモリ全展開）。

    Args:
        input_path: 入力 JSON のパス。
        limit: 先頭 N 件のみ処理（0 = 全件）。

    Yields:
        各レコードの dict。
    """
    with open(input_path, encoding="utf-8") as f:
        records = json.load(f)
    for i, record in enumerate(records):
        if limit > 0 and i >= limit:
            break
        yield record


def _iter_records_ijson(input_path: Path, limit: int):
    """ijson でストリーミング読み込みを行う。

    Args:
        input_path: 入力 JSON のパス。
        limit: 先頭 N 件のみ処理（0 = 全件）。

    Yields:
        各レコードの dict。
    """
    import ijson

    with open(input_path, "rb") as f:
        items = ijson.items(f, "item")
        for i, record in enumerate(items):
            if limit > 0 and i >= limit:
                break
            yield record


def _iter_records(input_path: Path, limit: int):
    """ijson があれば使い、なければ json にフォールバックする。

    Args:
        input_path: 入力 JSON のパス。
        limit: 先頭 N 件のみ処理（0 = 全件）。

    Yields:
        各レコードの dict。
    """
    try:
        import ijson as _  # noqa: F401

        yield from _iter_records_ijson(input_path, limit)
    except ImportError:
        print("[WARN] ijson not found, falling back to json (full load)", file=sys.stderr)
        yield from _iter_records_json(input_path, limit)


def _parse_ast_nodes(tree: list[dict[str, Any]]) -> list[ASTNode]:
    """tree リストを ASTNode リストに変換する。

    Args:
        tree: GumDiff.base_ast.tree の生 dict リスト。

    Returns:
        ASTNode のリスト。
    """
    return [ASTNode(**n) for n in tree]


def _parse_actions(actions: list[dict[str, Any]]) -> list[GumAction]:
    """actions リストを GumAction リストに変換する。

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


def process_record(
    record: dict[str, Any],
    matchers: list,
    enable_stage_b: bool = True,
) -> list[PatternMatch]:
    """1 件の MBDiff レコードに対して Stage A/B を実行する。

    Args:
        record: MBDiff.json の 1 レコード。
        matchers: 適用する matcher リスト。
        enable_stage_b: True の場合 Stage B（diff 連動）も実行する。

    Returns:
        PatternMatch のリスト。
    """
    mb_id = record.get("id", 0)
    diff = record.get("diff", {})

    base_ast = diff.get("base_ast", {})
    code = base_ast.get("code", "")
    tree_raw = base_ast.get("tree", [])
    nodes = _parse_ast_nodes(tree_raw)

    results: list[PatternMatch] = []

    # Stage A: BEFORE-only 検出
    for matcher in matchers:
        for pm in matcher.find(nodes, code, mb_id=mb_id):
            results.append(pm)

    if not enable_stage_b or not results:
        return results

    # Stage B: diff 連動フィルタ
    base_actions = _parse_actions(diff.get("base_actions", []))
    matches_raw = diff.get("matches", [])
    head_tree_raw = diff.get("head_ast", {}).get("tree", [])
    head_nodes = _parse_ast_nodes(head_tree_raw)
    matches = [(b, h) for b, h in matches_raw]

    updated = []
    for pm in results:
        updated.append(apply_diff_link(pm, base_actions, matches, head_nodes))
    return updated


def build_summary(all_matches: list[PatternMatch]) -> dict[str, Any]:
    """全マッチから summary.json 用の集計データを生成する。

    Args:
        all_matches: 全 PatternMatch リスト。

    Returns:
        summary dict。
    """
    summary: dict[int, dict] = {}
    for pid in range(1, 11):
        summary[pid] = {
            "pattern_id": pid,
            "total": 0,
            "by_confidence": {"high": 0, "medium": 0, "low": 0},
            "diff_linked": 0,
        }

    for pm in all_matches:
        pid = pm.pattern_id
        if pid not in summary:
            continue
        summary[pid]["total"] += 1
        summary[pid]["by_confidence"][pm.confidence] = summary[pid]["by_confidence"].get(pm.confidence, 0) + 1
        if pm.diff_linked:
            summary[pid]["diff_linked"] += 1

    return {"patterns": list(summary.values())}


def write_outputs(output_dir: Path, all_matches: list[PatternMatch]) -> None:
    """結果を output_dir に書き出す。

    Args:
        output_dir: 出力ディレクトリ。
        all_matches: 全 PatternMatch リスト。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # matches.jsonl
    matches_path = output_dir / "matches.jsonl"
    with open(matches_path, "w", encoding="utf-8") as f:
        for pm in all_matches:
            f.write(json.dumps(pm.__dict__, ensure_ascii=False) + "\n")
    print(f"Written: {matches_path} ({len(all_matches)} matches)")

    # summary.json
    summary = build_summary(all_matches)
    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"Written: {summary_path}")

    # samples/pattern_<id>/
    by_pid: dict[int, list[PatternMatch]] = defaultdict(list)
    for pm in all_matches:
        by_pid[pm.pattern_id].append(pm)

    for pid, pid_matches in sorted(by_pid.items()):
        sample_dir = output_dir / "samples" / f"pattern_{pid}"
        sample_dir.mkdir(parents=True, exist_ok=True)

        for confidence in ("high", "medium", "low"):
            conf_matches = [m for m in pid_matches if m.confidence == confidence]
            if not conf_matches:
                continue
            conf_path = sample_dir / f"{confidence}.jsonl"
            with open(conf_path, "w", encoding="utf-8") as f:
                for pm in conf_matches:
                    f.write(json.dumps(pm.__dict__, ensure_ascii=False) + "\n")

        # representative.md（上位 3 件のコード断片）
        rep_matches = sorted(pid_matches, key=lambda m: m.diff_linked, reverse=True)[:3]
        rep_path = sample_dir / "representative.md"
        with open(rep_path, "w", encoding="utf-8") as f:
            f.write(f"# Pattern {pid} 代表サンプル\n\n")
            for i, pm in enumerate(rep_matches, 1):
                f.write(f"## Sample {i}\n\n")
                f.write(f"- mb_id: {pm.mb_id}\n")
                f.write(f"- confidence: {pm.confidence}\n")
                f.write(f"- diff_linked: {pm.diff_linked}\n")
                f.write(f"- node_index: {pm.node_index}\n\n")
                f.write("```javascript\n")
                f.write(pm.snippet[:200])
                f.write("\n```\n\n")

        print(f"  Pattern {pid}: {len(pid_matches)} matches, {sum(1 for m in pid_matches if m.diff_linked)} diff_linked")


def main() -> None:
    """エントリポイント。"""
    parser = argparse.ArgumentParser(description="Slow pattern detection on MBDiff.json")
    parser.add_argument("--input", required=True, help="Input MBDiff.json path")
    parser.add_argument("--output-dir", default="outputs/tmp/slow_patterns", help="Output directory")
    parser.add_argument("--patterns", default="1,2,3,4,5,6,7,8,9,10", help="Comma-separated pattern IDs")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N records (0=all)")
    parser.add_argument("--no-stage-b", action="store_true", help="Disable Stage B (diff-link)")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    pattern_ids = [int(p.strip()) for p in args.patterns.split(",") if p.strip()]
    enable_stage_b = not args.no_stage_b

    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    matchers = _get_matchers(pattern_ids)
    print(f"Patterns: {[m.pattern_id for m in matchers]}")
    print(f"Input: {input_path}")
    print(f"Output: {output_dir}")
    print(f"Limit: {args.limit if args.limit > 0 else 'all'}")
    print(f"Stage B: {'enabled' if enable_stage_b else 'disabled'}")

    all_matches: list[PatternMatch] = []
    count = 0

    for record in tqdm(_iter_records(input_path, args.limit), desc="Processing", unit="rec"):
        matches = process_record(record, matchers, enable_stage_b=enable_stage_b)
        all_matches.extend(matches)
        count += 1

    print(f"Processed {count} records, found {len(all_matches)} matches total.")
    write_outputs(output_dir, all_matches)


if __name__ == "__main__":
    main()
