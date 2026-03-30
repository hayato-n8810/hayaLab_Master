"""事前分析（ループ有無・メソッド名の収集）

入力: data/MB_separate.json
出力: data/MB_loop_method.json

MB_separate の separate.setup/slow/fast それぞれを GumTree で AST にパースし、
- 反復処理（LOOP_TYPES）が含まれるか
- property_identifier として出現するメソッド名（collect_method_name）
を収集して、元コードと合わせた JSON を出力する。
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Any

from tqdm import tqdm

import hayalab
from hayalab.config import PathConfig


def analyze_snippet(code: str) -> dict[str, Any]:
    """コード片を AST 解析し，ループ有無とメソッド名を返す

    Args:
        code (str): 解析対象コード

    Returns:
        dict[str, Any]: 解析結果（コード、ループ有無、メソッド名リスト、エラー情報）
    """

    LOOP_TYPES: list[str] = [
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
    ]

    if not code:
        return {"code": "", "has_loop": False, "methods": []}

    try:
        ast = hayalab.gum_parse(code)
    except Exception:
        return {"code": code, "has_loop": False, "methods": [], "error": "parse_failed"}

    if ast is None:
        return {"code": code, "has_loop": False, "methods": [], "error": "parse_failed"}

    label_counts = hayalab.count_label(ast, LOOP_TYPES)
    has_loop = any(count > 0 for count in label_counts.values())
    methods = hayalab.collect_method_name(ast)

    return {"code": code, "has_loop": has_loop, "methods": methods}


def process_pair(mb_pair: dict[str, Any]) -> dict[str, Any]:
    """1件分（setup/slow/fast）を解析して返す。"""
    separate = mb_pair.get("separate") or {}
    setup_code = separate.get("setup", "")
    slow_code = separate.get("slow", "")
    fast_code = separate.get("fast", "")

    setup = analyze_snippet(setup_code)
    slow = analyze_snippet(slow_code)
    fast = analyze_snippet(fast_code)

    result: dict[str, Any] = {
        "id": mb_pair.get("id"),
        "setup": setup,
        "slow": slow,
        "fast": fast,
    }
    return result


if __name__ == "__main__":
    config = PathConfig()

    origin_data = hayalab.read_json(f"{config.processed}/MB_separate.json")

    max_workers = 1  # 同時実行プロセス数
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        results = list(tqdm(executor.map(process_pair, origin_data), total=len(origin_data)))

    failed_ids = [r["id"] for r in results if any((r.get(k, {}) or {}).get("error") == "parse_failed" for k in ("setup", "slow", "fast"))]
    if failed_ids:
        print(f"\nParse failed for IDs: {', '.join(map(str, failed_ids))}")

    results.sort(key=lambda x: x["id"])

    output_path = f"{config.outputs}/pattern/MB_pre_analysis.json"
    hayalab.write_json(output_path, results)
    print(f"Created: {output_path} ({len(results)} items)")

    loop_pair_count = sum(1 for r in results if (r.get("slow") or {}).get("has_loop") or (r.get("fast") or {}).get("has_loop"))
    print(f"slowかfastにループを含むMBペアの数: {loop_pair_count}")
