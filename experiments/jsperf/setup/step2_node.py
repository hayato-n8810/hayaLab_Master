"""Step 2: Step 1 で生成した program_<i>.js を Node で並列実行し、Node 成功タグを付与する.

`outputs/jsperf/setup/step1/slug_id/program_<i>.js` を入力とし、
worker=35 の並列で `node` 実行 (タイムアウトなし、エラー時 1 回だけ再実行) の後、
`outputs/jsperf/setup/step2/{results.jsonl, tags.jsonl, summary.json}` を保存する.
"""

from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import hayalab
from hayalab.config import PathConfig
from hayalab.utils.file.exec import classify_node_error, run_node

# --- Constants ------------------------------------------------------
MAX_WORKERS: int = 25
NODE_BIN: str = "node"
TIMEOUT: float = 180.0  # seconds
ERROR_TYPE_KEYS: tuple[str, ...] = (
    "ReferenceError",
    "TypeError",
    "SyntaxError",
    "RangeError",
    "ModuleNotFound",
    "OutOfMemory",
    "Timeout",
    "OtherError",
)


def _run_program_with_retry(job: tuple[str, str, int, Path]) -> dict:
    """1 プログラム分の Node 実行 (エラー時 1 回だけリトライ) を行い、結果レコードを返す.

    Args:
        job: `(slug_id, slug, test_idx, js_path)` タプル.

    Returns:
        dict: results.jsonl 1 行分の辞書
        (`slug_id` / `slug` / `test_idx` / `path` / `status` / `exit_code` /
        `error_type` / `stderr_head` / `elapsed`).
    """
    slug_id, slug, test_idx, js_path = job
    result = run_node(js_path, node_bin=NODE_BIN, timeout=TIMEOUT)
    if result["status"] != "success":
        result = run_node(js_path, node_bin=NODE_BIN, timeout=TIMEOUT)
    if result["status"] == "success":
        error_type: str | None = None
    elif result["status"] == "timeout":
        error_type = "Timeout"
    else:
        error_type = classify_node_error(result["stderr_head"])
    return {
        "slug_id": slug_id,
        "slug": slug,
        "test_idx": test_idx,
        "path": f"{slug_id}/program_{test_idx}.js",
        "status": result["status"],
        "exit_code": result["exit_code"],
        "error_type": error_type,
        "stderr_head": result["stderr_head"],
        "elapsed": result["elapsed"],
    }


if __name__ == "__main__":
    # --- Section 1: パス定義 ---
    CONFIG = PathConfig()
    STEP1_DIR = CONFIG.outputs / "jsperf" / "setup" / "step1"
    STEP2_DIR = CONFIG.outputs / "jsperf" / "setup" / "step2"
    STEP2_DIR.mkdir(parents=True, exist_ok=True)
    if not STEP1_DIR.exists():
        raise SystemExit(f"input not found: {STEP1_DIR}")

    # --- Section 2: ジョブ列挙 (meta.json から slug/test_count を読み込み) ---
    jobs: list[tuple[str, str, int, Path]] = []
    bench_ids: list[str] = []
    for meta_path in sorted(STEP1_DIR.glob("*/meta.json")):
        meta = hayalab.read_json(meta_path)
        slug_id: str = meta["slug_id"]
        slug: str = meta["slug"]
        bench_dir = meta_path.parent
        bench_ids.append(slug_id)
        for i in range(int(meta["test_count"])):
            jobs.append((slug_id, slug, i, bench_dir / f"program_{i}.js"))

    print(f"benchmarks: {len(bench_ids)}")
    print(f"total programs: {len(jobs)}")

    # --- Section 3: 並列実行 ---
    start = time.perf_counter()
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for r in executor.map(_run_program_with_retry, jobs):
            results.append(r)
    elapsed_sec = time.perf_counter() - start

    # --- Section 4: results.jsonl / tags.jsonl の書き出し (ソート済み) ---
    results.sort(key=lambda x: (x["slug_id"], x["test_idx"]))
    hayalab.write_jsonl(STEP2_DIR / "results.jsonl", results)

    tags: list[dict] = [
        {
            "slug_id": r["slug_id"],
            "slug": r["slug"],
            "test_idx": r["test_idx"],
            "node_success": r["status"] == "success",
        }
        for r in results
    ]
    hayalab.write_jsonl(STEP2_DIR / "tags.jsonl", tags)

    # --- Section 5: 集計 ---
    status_counts_c: Counter[str] = Counter(r["status"] for r in results)
    error_type_counts_c: Counter[str] = Counter(r["error_type"] for r in results if r["error_type"])

    status_counts: dict[str, int] = {
        "success": status_counts_c.get("success", 0),
        "error": status_counts_c.get("error", 0),
        "timeout": status_counts_c.get("timeout", 0),
    }
    error_type_counts: dict[str, int] = {k: error_type_counts_c.get(k, 0) for k in ERROR_TYPE_KEYS}

    bench_success_map: dict[str, list[bool]] = {sid: [] for sid in bench_ids}
    for r in results:
        bench_success_map[r["slug_id"]].append(r["status"] == "success")

    bench_all_success = 0
    bench_all_failed = 0
    bench_partial = 0
    bench_zero_tests = 0
    for flags in bench_success_map.values():
        if not flags:
            bench_zero_tests += 1
        elif all(flags):
            bench_all_success += 1
        elif not any(flags):
            bench_all_failed += 1
        else:
            bench_partial += 1

    summary = {
        "elapsed_sec": elapsed_sec,
        "max_workers": MAX_WORKERS,
        "total_js": len(results),
        "status_counts": status_counts,
        "error_type_counts": error_type_counts,
        "benchmark_summary": {
            "benchmarks_total": len(bench_ids),
            "benchmarks_all_success": bench_all_success,
            "benchmarks_partial_success": bench_partial,
            "benchmarks_all_failed": bench_all_failed,
            "benchmarks_zero_tests": bench_zero_tests,
        },
    }
    hayalab.write_json(STEP2_DIR / "summary.json", summary)

    # --- Section 6: 進捗レポート ---
    print(f"elapsed: {elapsed_sec:.1f}s")
    print(f"status_counts: {status_counts}")
    print(f"error_type_counts: {error_type_counts}")
    print(f"benchmark_summary: {summary['benchmark_summary']}")
    print(f"outputs written to: {STEP2_DIR}")
