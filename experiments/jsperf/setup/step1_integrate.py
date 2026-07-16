"""Step 1: inline `<script>` + setup + test + teardown を統合し program_<i>.js を生成する.

`data/processed/benchmarks_latest_revision.json` を入力とし、
`outputs/jsperf/setup/step1/` 配下に slug_id 別のディレクトリで
`program_<i>.js` / `page_html.html` / `meta.json` を書き出し、
全体集計 `summary.json` とユニーク CDN URL 集合 `cdn_list.json` を保存する。
"""

from __future__ import annotations

import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import repeat
from pathlib import Path

from tqdm import tqdm

import hayalab
from hayalab.config import PathConfig
from hayalab.jsperf.preparation import (
    classify_preparation_html,
    extract_external_script_srcs,
    extract_inline_scripts,
    has_dom_elements,
    strip_inline_scripts,
)

# --- Constants ------------------------------------------------------
WORKER_COUNT: int = max(1, (os.cpu_count() or 1) - 1)
CHUNK_SIZE: int = 6
SLUG_ID_WIDTH: int = 5


# --- Helpers --------------------------------------------------------
def _slug_id(index: int) -> str:
    """入力並び順のインデックスから一意な連番識別子を組み立てる.

    Args:
        index: `benchmarks[i]` の 0 始まりインデックス.

    Returns:
        str: ゼロ埋め済み連番 (幅は `SLUG_ID_WIDTH`).
    """
    return f"{index:0{SLUG_ID_WIDTH}d}"


def _build_program(inline_scripts: list[str], setup: str, test_code: str, teardown: str) -> str:
    """1 テスト分の統合済み実行 JS 本文を組み立てる.

    Args:
        inline_scripts: preparation_html から抽出したインライン script の中身 (DOM 順).
        setup: ベンチマークの setup フィールド.
        test_code: 対象 test の code フィールド.
        teardown: ベンチマークの teardown フィールド.

    Returns:
        str: 統合済み JS 文字列 (末尾に改行).
    """
    segments: list[str] = []
    inline_joined = "\n".join(inline_scripts)
    if inline_joined.strip():
        segments.append(inline_joined)
    if setup.strip():
        segments.append(setup)
    if test_code.strip():
        segments.append(test_code)
    if teardown.strip():
        segments.append(teardown)
    return "\n".join(segments) + ("\n" if segments else "")


def _process_benchmark(index: int, benchmark: dict, out_root: Path) -> dict:
    """1 ベンチマーク分のファイル群を書き出し、集計用サマリを返す.

    Args:
        index: `benchmarks[i]` の 0 始まりインデックス. slug_id の元。
        benchmark: 入力 JSON の `benchmarks[i]` エントリ.
        out_root: 出力ルート (`outputs/jsperf/setup/step1/benchmark`).

    Returns:
        dict: category / test_count / cdn_urls / has_dom_elements / has_inline_scripts /
        slug_id を含む集計用辞書.
    """
    slug: str = benchmark["slug"]
    revision: int = benchmark["revision"]
    slug_id: str = _slug_id(index)

    prep_html: str = benchmark.get("preparation_html") or ""
    setup: str = benchmark.get("setup") or ""
    teardown: str = benchmark.get("teardown") or ""
    tests: list[dict] = benchmark.get("tests") or []

    inline_scripts = extract_inline_scripts(prep_html)
    external_srcs = extract_external_script_srcs(prep_html)
    stripped_html = strip_inline_scripts(prep_html) if prep_html.strip() else ""
    dom_present = has_dom_elements(stripped_html) if stripped_html else False
    category = classify_preparation_html(prep_html)

    cdn_urls_unique: list[str] = sorted(set(external_srcs))

    bench_dir = out_root / slug_id
    bench_dir.mkdir(parents=True, exist_ok=True)

    for i, t in enumerate(tests):
        test_code = t.get("code") or ""
        body = _build_program(inline_scripts, setup, test_code, teardown)
        (bench_dir / f"program_{i}.js").write_text(body, encoding="utf-8")

    if stripped_html.strip():
        (bench_dir / "page_html.html").write_text(stripped_html, encoding="utf-8")

    meta = {
        "slug": slug,
        "slug_id": slug_id,
        "revision": revision,
        "title": benchmark.get("title") or "",
        "url": benchmark.get("url") or "",
        "test_count": len(tests),
        "cdn_urls": cdn_urls_unique,
        "has_dom_elements": dom_present,
        "has_inline_scripts": len(inline_scripts) > 0,
    }
    hayalab.write_json(bench_dir / "meta.json", meta)

    return {
        "slug_id": slug_id,
        "category": category,
        "test_count": len(tests),
        "cdn_urls": cdn_urls_unique,
        "has_dom_elements": dom_present,
        "has_inline_scripts": len(inline_scripts) > 0,
    }


if __name__ == "__main__":
    # --- Section 1: パス定義 ---
    CONFIG = PathConfig()
    INPUT_JSON = CONFIG.processed / "benchmarks_latest_revision.json"
    OUTPUT_ROOT = CONFIG.outputs / "jsperf" / "setup" / "step1"
    OUTPUT_BENCH = OUTPUT_ROOT / "benchmark"
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if not INPUT_JSON.exists():
        raise SystemExit(f"input not found: {INPUT_JSON}")

    # --- Section 2: 入力ロード ---
    data = hayalab.read_json(INPUT_JSON)
    benchmarks: list[dict] = data["benchmarks"]
    print(f"loaded benchmarks: {len(benchmarks)}")

    # --- Section 3: 並列処理 ---
    per_bench_results: list[dict] = []
    with ProcessPoolExecutor(max_workers=WORKER_COUNT) as executor:
        for result in tqdm(
            executor.map(_process_benchmark, range(len(benchmarks)), benchmarks, repeat(OUTPUT_BENCH), chunksize=CHUNK_SIZE),
            total=len(benchmarks),
            desc="step1",
        ):
            per_bench_results.append(result)

    # --- Section 4: 全体集計 ---
    category_counter: Counter[str] = Counter(r["category"] for r in per_bench_results)
    test_count_counter: Counter[int] = Counter(r["test_count"] for r in per_bench_results)
    all_cdn_urls: set[str] = set()
    total_programs: int = 0
    for r in per_bench_results:
        all_cdn_urls.update(r["cdn_urls"])
        total_programs += r["test_count"]
    sorted_cdn_urls: list[str] = sorted(all_cdn_urls)

    category_breakdown: dict[str, int] = {k: category_counter.get(k, 0) for k in ("empty", "inline_only", "external_only", "with_dom")}
    test_count_histogram: dict[str, int] = {str(k): test_count_counter[k] for k in sorted(test_count_counter)}

    summary = {
        "total_input": len(benchmarks),
        "category_breakdown": category_breakdown,
        "test_count_histogram": test_count_histogram,
        "total_programs": total_programs,
        "cdn_url_count": len(sorted_cdn_urls),
    }

    # --- Section 5: 出力保存 ---
    hayalab.write_json(OUTPUT_ROOT / "summary.json", summary)
    hayalab.write_json(OUTPUT_ROOT / "cdn_list.json", sorted_cdn_urls)

    # --- Section 6: 件数レポート ---
    print(f"total_input: {summary['total_input']}")
    print(f"category_breakdown: {category_breakdown}")
    print(f"test_count_histogram: {test_count_histogram}")
    print(f"total_programs: {total_programs}")
    print(f"unique_cdn_urls: {len(sorted_cdn_urls)}")
    print(f"outputs written to: {OUTPUT_ROOT}")
