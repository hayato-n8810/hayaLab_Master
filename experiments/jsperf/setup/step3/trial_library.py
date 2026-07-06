"""Step 3 の単一ライブラリ試行スクリプト.

指定ライブラリを step3 の npm ワークスペースにインストールし、
step2 で Node 失敗 (`node_success=false`) となった program のうち
`meta.json.cdn_urls` が `--url-pattern` にマッチするものに
`require` 挿入を施して再実行し、結果を保存する.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import hayalab
from hayalab.config import PathConfig
from hayalab.utils.file.exec import classify_node_error, run_node

# --- Constants ------------------------------------------------------
DEFAULT_MAX_WORKERS: int = 20
# DEFAULT_CHUNK_SIZE: int = 500
NODE_BIN: str = "node"
ERROR_TYPE_KEYS: tuple[str, ...] = (
    "ReferenceError",
    "TypeError",
    "SyntaxError",
    "RangeError",
    "ModuleNotFound",
    "OutOfMemory",
    "OtherError",
)


# --- Helpers (関数化: 複数箇所または per-record worker) -----------------
def _write_jsonl(path: Path, records: list[dict]) -> None:
    """レコード列を JSONL として書き出す (順序保存)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _url_matches(cdn_urls: list[str], pattern: str) -> bool:
    """CDN URL リストに pattern (case-insensitive substring) が含まれるか判定する."""
    p = pattern.lower()
    return any(p in url.lower() for url in cdn_urls)


_INJECTED_PREFIX: str = "// [step3-trial] injected require\n"


def _make_import_line(binding: str, library: str) -> str:
    """`require` 挿入行を組み立てる."""
    return f"const {binding} = require({json.dumps(library)});\n"


def _run_trial_program(job: tuple[str, str, int, str, str, Path, Path]) -> dict:
    """1 program の trial 実行 (per-record worker; PoolExecutor 用).

    Args:
        job: (slug_id, slug, test_idx, library, binding, src_program, dst_program) のタプル.
            `src_program` は step1 の元 JS、`dst_program` は require 挿入後の書き出し先.

    Returns:
        dict: 実行結果 (results.jsonl 1 行分).
    """
    slug_id, slug, test_idx, library, binding, src_program, dst_program = job

    original: str = src_program.read_text(encoding="utf-8")
    injected: str = _INJECTED_PREFIX + _make_import_line(binding, library) + original
    dst_program.parent.mkdir(parents=True, exist_ok=True)
    dst_program.write_text(injected, encoding="utf-8")

    res: dict = run_node(dst_program, node_bin=NODE_BIN, timeout=None)
    error_type: str | None = None
    if res["status"] != "success":
        error_type = classify_node_error(res["stderr_head"])

    return {
        "slug_id": slug_id,
        "slug": slug,
        "test_idx": test_idx,
        "library": library,
        "path": f"{slug_id}/program_{test_idx}.js",
        "status": res["status"],
        "exit_code": res["exit_code"],
        "error_type": error_type,
        "stderr_head": res["stderr_head"],
        "elapsed": res["elapsed"],
    }


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数パース ---
    parser = argparse.ArgumentParser(description="Step3: single-library trial. npm install → inject require → run failed programs.")
    parser.add_argument("--library", required=True, help="npm package name (e.g., lodash)")
    parser.add_argument("--version", required=True, help="npm version spec (e.g., ^4.17.21 or 4.17.21)")
    parser.add_argument("--binding", required=True, help="variable name for the injected require (e.g., _)")
    parser.add_argument(
        "--url-pattern",
        required=True,
        help="case-insensitive substring; program is a trial target when its meta.json.cdn_urls contains this",
    )
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument(
        "--skip-npm-install",
        action="store_true",
        help="skip `npm install`; use pre-installed node_modules",
    )
    args = parser.parse_args()

    library: str = args.library
    version: str = args.version
    binding: str = args.binding
    url_pattern: str = args.url_pattern
    max_workers: int = args.max_workers

    # --- Section 2: パス解決 ---
    CONFIG = PathConfig()
    STEP1_DIR: Path = CONFIG.outputs / "jsperf" / "setup" / "step1"
    STEP2_TAGS: Path = CONFIG.outputs / "jsperf" / "setup" / "step2" / "tags.jsonl"
    STEP3_DIR: Path = CONFIG.root / "experiments" / "jsperf" / "setup" / "step3"
    TRIAL_DIR: Path = CONFIG.outputs / "jsperf" / "setup" / "step3" / "trials" / library
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)

    if not STEP2_TAGS.exists():
        raise SystemExit(f"missing input: {STEP2_TAGS}")
    if not STEP1_DIR.exists():
        raise SystemExit(f"missing input: {STEP1_DIR}")

    print(f"[trial] library={library} version={version} binding={binding} url_pattern={url_pattern}")
    print(f"[trial] trial output dir: {TRIAL_DIR}")

    # --- Section 3: npm install (Docker 内で実行される想定) ---
    if not args.skip_npm_install:
        install_start = time.perf_counter()
        cmd: list[str] = ["npm", "install", "--save", f"{library}@{version}"]
        print(f"[trial] running: {' '.join(cmd)}  (cwd={STEP3_DIR})")
        install_res = subprocess.run(cmd, cwd=STEP3_DIR, capture_output=True, text=True)
        if install_res.returncode != 0:
            print(install_res.stdout, file=sys.stderr)
            print(install_res.stderr, file=sys.stderr)
            raise SystemExit(f"npm install failed with exit code {install_res.returncode}")
        print(f"[trial] npm install ok ({time.perf_counter() - install_start:.1f}s)")

    # --- Section 4: 失敗 program 一覧と URL パターン一致でフィルタ ---
    failed_tags: list[dict] = []
    with STEP2_TAGS.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if not rec.get("node_success", False):
                failed_tags.append(rec)
    print(f"[trial] step2 node_success=false: {len(failed_tags)}")

    meta_cache: dict[str, dict] = {}
    jobs: list[tuple[str, str, int, str, str, Path, Path]] = []
    matched_benchmarks: set[str] = set()
    for rec in failed_tags:
        slug_id: str = rec["slug_id"]
        slug: str = rec["slug"]
        test_idx: int = rec["test_idx"]

        meta = meta_cache.get(slug_id)
        if meta is None:
            meta_path = STEP1_DIR / slug_id / "meta.json"
            if not meta_path.exists():
                continue
            meta = hayalab.read_json(meta_path)
            meta_cache[slug_id] = meta

        cdn_urls: list[str] = list(meta.get("cdn_urls", []))
        if not _url_matches(cdn_urls, url_pattern):
            continue

        src = STEP1_DIR / slug_id / f"program_{test_idx}.js"
        if not src.exists():
            continue
        dst = TRIAL_DIR / slug_id / f"program_{test_idx}.js"
        jobs.append((slug_id, slug, test_idx, library, binding, src, dst))
        matched_benchmarks.add(slug_id)

    print(f"[trial] matched benchmarks: {len(matched_benchmarks)}")
    print(f"[trial] target programs: {len(jobs)}")

    if not jobs:
        summary = {
            "library": library,
            "version": version,
            "binding": binding,
            "url_pattern": url_pattern,
            "matched_benchmarks": 0,
            "target_programs": 0,
            "status_counts": {"success": 0, "error": 0, "timeout": 0},
            "error_type_counts": {k: 0 for k in ERROR_TYPE_KEYS},
        }
        hayalab.write_json(TRIAL_DIR / "summary.json", summary)
        _write_jsonl(TRIAL_DIR / "results.jsonl", [])
        print("[trial] no targets matched — wrote empty results.")
        raise SystemExit(0)

    # --- Section 5: 並列実行 ---
    start = time.perf_counter()
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        for r in executor.map(_run_trial_program, jobs):
            results.append(r)
    elapsed_sec = time.perf_counter() - start

    # --- Section 6: 結果書き出しと集計 ---
    results.sort(key=lambda x: (x["slug_id"], x["test_idx"]))
    _write_jsonl(TRIAL_DIR / "results.jsonl", results)

    status_counts_c: Counter[str] = Counter(r["status"] for r in results)
    error_type_counts_c: Counter[str] = Counter(r["error_type"] for r in results if r["error_type"])
    status_counts = {
        "success": status_counts_c.get("success", 0),
        "error": status_counts_c.get("error", 0),
        "timeout": status_counts_c.get("timeout", 0),
    }
    error_type_counts = {k: error_type_counts_c.get(k, 0) for k in ERROR_TYPE_KEYS}

    bench_flags: dict[str, list[bool]] = {sid: [] for sid in sorted(matched_benchmarks)}
    for r in results:
        bench_flags[r["slug_id"]].append(r["status"] == "success")
    bench_all_success = sum(1 for f in bench_flags.values() if f and all(f))
    bench_all_failed = sum(1 for f in bench_flags.values() if f and not any(f))
    bench_partial = sum(1 for f in bench_flags.values() if f and any(f) and not all(f))

    summary = {
        "library": library,
        "version": version,
        "binding": binding,
        "url_pattern": url_pattern,
        "elapsed_sec": elapsed_sec,
        "max_workers": max_workers,
        "matched_benchmarks": len(matched_benchmarks),
        "target_programs": len(jobs),
        "status_counts": status_counts,
        "error_type_counts": error_type_counts,
        "benchmark_summary": {
            "benchmarks_all_success": bench_all_success,
            "benchmarks_partial_success": bench_partial,
            "benchmarks_all_failed": bench_all_failed,
        },
    }
    hayalab.write_json(TRIAL_DIR / "summary.json", summary)

    # --- Section 7: 進捗レポート ---
    print(f"[trial] elapsed: {elapsed_sec:.1f}s")
    print(f"[trial] status_counts: {status_counts}")
    print(f"[trial] error_type_counts: {error_type_counts}")
    print(f"[trial] benchmark_summary: {summary['benchmark_summary']}")
    print(f"[trial] outputs: {TRIAL_DIR}")
