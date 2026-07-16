"""Step 3 統合スクリプト: cdn_list_resolve.json → package.json 自動生成 → npm install → require 挿入 → Node 実行 → 集計.

`experiments/jsperf/setup/cdn_list_resolve.json` を単一情報源とし、対応するライブラリを
`experiments/jsperf/setup/step3/package.json` として自動生成、`npm install` の後、
step2 で全 program に node_success タグが付いていない対象ベンチマークについて、
そのベンチマーク内の**全** program に対し (step2 で成功していたものも含めて一律)、
meta.json.cdn_urls から必要ライブラリを判定して require を挿入し Node で実行する.

入力:
- `experiments/jsperf/setup/cdn_list_resolve.json`
- `outputs/jsperf/setup/step1/<slug_id>/(meta.json, program_<i>.js)`
- `outputs/jsperf/setup/step2/tags.jsonl`

出力: `outputs/jsperf/setup/step3/`
- `benchmark/<slug_id>/program_<i>.js`: require 挿入済み JS (試行対象になったベンチマークのみ)
- `results.jsonl`: step3 実行結果 (per program)
- `tags.jsonl`: 全 program のタグ — `node_success` (step2 の結果そのまま) と `npm_success` (step3 の npm 注入後に成功したか) を独立に保持
- `summary.json`: 集計

なお、npm パッケージは `experiments/jsperf/setup/step3/package.json` (単一) で管理
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import hayalab
from hayalab.config import PathConfig
from hayalab.utils.file.exec import classify_node_error, run_node

# --- Constants ------------------------------------------------------
DEFAULT_MAX_WORKERS: int = 20
NODE_BIN: str = "node"
NODE_TIMEOUT: float = 180.0
ERROR_TYPE_KEYS: tuple[str, ...] = (
    "ReferenceError",
    "TypeError",
    "SyntaxError",
    "RangeError",
    "ModuleNotFound",
    "OutOfMemory",
    "OtherError",
)


# --- Helpers (per-record 処理) -----------------
def _resolve_libs_for_urls(cdn_urls: list[str], resolver: list[dict]) -> list[tuple[str, str, str | None]]:
    """各ベンチマークの CDN URL リストに対応するライブラリの (package, binding) 組を返す.
        package: npm パッケージ名, binding: require での変数名

    Args:
        cdn_urls (list[str]): 各ベンチマークのCDNのURL（ meta.json.cdn_urls )
        resolver (list[dict]): cdn_list_resolve.json の libraries 配列

    Returns:
        list[tuple[str, str]]:
            (ライブラリ名, バインディング名) の組のリスト.
    """
    hits: list[tuple[str, str]] = []
    seen_pkgs: set[str] = set()
    seen_bindings: set[str] = set()
    for entry in resolver:
        patterns: list[str] = [p.lower() for p in entry["patterns"]]
        pkg: str = entry["package"]
        binding: str = entry["binding"]
        if pkg in seen_pkgs or binding in seen_bindings:
            continue
        for u in cdn_urls:
            ul = u.lower()
            if any(pat in ul for pat in patterns):
                hits.append((pkg, binding))
                seen_pkgs.add(pkg)
                seen_bindings.add(binding)
                break
    return hits


def _run_step3_program(
    job: tuple[str, str, int, tuple[tuple[str, str], ...], Path, Path],
) -> dict:
    """1 program に require を挿入し node で実行する per-record worker.

    Args:
        job (tuple[str, str, int, tuple[tuple[str, str], ...], Path, Path]): 実行するプログラム1件の情報

    Returns:
        dict: results.jsonl 1 行分（id，test_code，ライブラリ，error_type，エラー出力）
    """
    slug_id, slug, test_idx, libs, src_program, dst_program = job

    lines: list[str] = []
    for pkg, binding in libs:
        lines.append("// Package injected\n")
        lines.append(f"const {binding} = require({json.dumps(pkg)});\n")
    lines.append("\n// Test program source code:\n")
    require_block: str = "".join(lines)
    original: str = src_program.read_text(encoding="utf-8")
    injected: str = require_block + original
    dst_program.parent.mkdir(parents=True, exist_ok=True)
    dst_program.write_text(injected, encoding="utf-8")

    res: dict = run_node(dst_program, node_bin=NODE_BIN, timeout=NODE_TIMEOUT)
    error_type: str | None = None
    if res["status"] != "success":
        error_type = classify_node_error(res["stderr_head"])

    return {
        "slug_id": slug_id,
        "slug": slug,
        "test_idx": test_idx,
        "libraries": [pkg for pkg, _b in libs],
        "n_libraries": len(libs),
        "path": f"benchmark/{slug_id}/program_{test_idx}.js",
        "status": res["status"],
        "exit_code": res["exit_code"],
        "error_type": error_type,
        "stderr_head": res["stderr_head"],
        "elapsed": res["elapsed"],
    }


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数パース ---
    parser = argparse.ArgumentParser(description="Step3 integrated: resolve → npm install → inject → run → aggregate.")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument(
        "--skip-npm-install",
        action="store_true",
        help="skip package.json regeneration and npm install (use existing node_modules)",
    )
    args = parser.parse_args()

    # --- Section 2: パス解決 ---
    CONFIG = PathConfig()

    # 入力
    STEP1_BENCH: Path = CONFIG.outputs / "jsperf" / "setup" / "step1" / "benchmark"
    STEP2_TAGS: Path = CONFIG.outputs / "jsperf" / "setup" / "step2" / "tags.jsonl"
    STEP3_WORKDIR: Path = CONFIG.experiments / "jsperf" / "setup" / "step3"
    RESOLVE_PATH: Path = STEP3_WORKDIR / "cdn_list_resolve.json"

    # 出力先
    STEP3_OUT: Path = CONFIG.outputs / "jsperf" / "setup" / "step3"
    STEP3_BENCH: Path = STEP3_OUT / "benchmark"
    STEP3_OUT.mkdir(parents=True, exist_ok=True)
    STEP3_BENCH.mkdir(parents=True, exist_ok=True)

    for p in (STEP2_TAGS, STEP1_BENCH, RESOLVE_PATH):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")

    resolver_data: dict = hayalab.read_json(RESOLVE_PATH)
    resolver: list[dict] = resolver_data["libraries"]
    print(f"[step3] resolve libraries: {len(resolver)}")

    # --- Section 3: 各ライブラリを @latest で 1 つずつ npm install (失敗しても継続) ---
    if not args.skip_npm_install:
        install_start = time.perf_counter()
        succeeded_installs: list[str] = []
        failed_installs: list[dict] = []

        for entry in sorted(resolver, key=lambda e: e["package"]):
            lib: str = entry["package"]
            install_res = subprocess.run(
                ["npm", "install", "--save", f"{lib}@latest"],
                cwd=STEP3_WORKDIR,
                capture_output=True,
                text=True,
            )
            if install_res.returncode != 0:
                stderr_tail: str = (install_res.stderr or "")[-2000:]
                failed_installs.append(
                    {
                        "lib": lib,
                        "exit_code": install_res.returncode,
                        "stderr_tail": stderr_tail,
                    }
                )
                print(
                    f"[step3] npm install {lib}@latest FAILED (exit {install_res.returncode})",
                    file=sys.stderr,
                )
                continue
            succeeded_installs.append(lib)
            print(f"[step3] npm install {lib}@latest ok")

        install_elapsed: float = time.perf_counter() - install_start
        print(f"[step3] install phase done ({install_elapsed:.1f}s): success={len(succeeded_installs)}, failed={len(failed_installs)}")
        if failed_installs:
            print("[step3] failed installs:")
            for f in failed_installs:
                print(f"  - {f['lib']}: exit={f['exit_code']}")

        hayalab.write_json(
            STEP3_OUT / "install_report.json",
            {
                "elapsed_sec": install_elapsed,
                "succeeded": succeeded_installs,
                "failed": failed_installs,
            },
        )

    # --- Section 4: step2 タグ読み込み ---
    step2_tags: list[dict] = hayalab.read_jsonl(STEP2_TAGS)
    n_step2_success: int = sum(1 for r in step2_tags if r.get("node_success", False))
    print(f"[step3] step2 tags total:  {len(step2_tags)}")
    print(f"[step3] step2 success:     {n_step2_success}")
    print(f"[step3] step2 failed:      {len(step2_tags) - n_step2_success}")

    # --- Section 5: 対象ベンチマーク特定 + ベンチマーク内全 program のジョブ生成 ---
    bench_tests: dict[str, list[dict]] = defaultdict(list)
    for rec in step2_tags:
        bench_tests[rec["slug_id"]].append(rec)

    target_slug_ids: set[str] = {slug_id for slug_id, recs in bench_tests.items() if not all(r.get("node_success", False) for r in recs)}
    print(f"[step3] target benchmarks (not all Step2 node_success): {len(target_slug_ids)}")

    meta_cache: dict[str, dict] = {}
    jobs: list[tuple[str, str, int, tuple[tuple[str, str], ...], Path, Path]] = []
    skipped_bench_no_meta: int = 0
    skipped_bench_no_lib: int = 0
    lib_count_dist: Counter[int] = Counter()
    for slug_id in sorted(target_slug_ids):
        meta_path = STEP1_BENCH / slug_id / "meta.json"
        if not meta_path.exists():
            skipped_bench_no_meta += 1
            continue
        meta = hayalab.read_json(meta_path)
        meta_cache[slug_id] = meta

        cdn_urls: list[str] = list(meta.get("cdn_urls", []))
        libs: list[tuple[str, str]] = _resolve_libs_for_urls(cdn_urls, resolver)
        if not libs:
            skipped_bench_no_lib += 1
            continue
        lib_count_dist[len(libs)] += 1

        for rec in bench_tests[slug_id]:
            test_idx: int = rec["test_idx"]
            slug: str = rec["slug"]
            src = STEP1_BENCH / slug_id / f"program_{test_idx}.js"
            if not src.exists():
                continue
            dst = STEP3_BENCH / slug_id / f"program_{test_idx}.js"
            jobs.append((slug_id, slug, test_idx, tuple(libs), src, dst))

    injected_bench_count: int = len(target_slug_ids) - skipped_bench_no_meta - skipped_bench_no_lib
    print(f"[step3] skipped benchmarks (no meta.json):      {skipped_bench_no_meta}")
    print(f"[step3] skipped benchmarks (no resolvable lib): {skipped_bench_no_lib}")
    print(f"[step3] injected benchmarks:                    {injected_bench_count}")
    print(f"[step3] injected programs:                      {len(jobs)}")
    print(f"[step3] libs-per-benchmark dist:                {dict(sorted(lib_count_dist.items()))}")

    # --- Section 6: 並列実行 ---
    results: list[dict] = []
    elapsed_sec: float = 0.0
    if jobs:
        start = time.perf_counter()
        with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
            for r in executor.map(_run_step3_program, jobs):
                results.append(r)
        elapsed_sec = time.perf_counter() - start
        results.sort(key=lambda x: (x["slug_id"], x["test_idx"]))
    else:
        print("[step3] no target jobs — skipping node execution.")

    # --- Section 7: results.jsonl / tags.jsonl 書き出し ---
    # node_success は step2 の結果をそのまま保持し、step3 (npm 注入後) の結果は
    # npm_success として別タグに記録する (注入対象外の program は npm_success=false)
    hayalab.write_jsonl(STEP3_OUT / "results.jsonl", results)

    step3_result_map: dict[tuple[str, int], str] = {(r["slug_id"], r["test_idx"]): r["status"] for r in results}
    tags_out: list[dict] = []
    for rec in step2_tags:
        key: tuple[str, int] = (rec["slug_id"], rec["test_idx"])
        tags_out.append(
            {
                "slug_id": rec["slug_id"],
                "slug": rec["slug"],
                "test_idx": rec["test_idx"],
                "node_success": bool(rec.get("node_success", False)),
                "npm_success": step3_result_map.get(key) == "success",
            }
        )
    tags_out.sort(key=lambda x: (x["slug_id"], x["test_idx"]))
    hayalab.write_jsonl(STEP3_OUT / "tags.jsonl", tags_out)

    # --- Section 8: 集計 (summary.json) ---
    status_counts_c: Counter[str] = Counter(r["status"] for r in results)
    error_type_counts_c: Counter[str] = Counter(r["error_type"] for r in results if r["error_type"])
    status_counts = {
        "success": status_counts_c.get("success", 0),
        "error": status_counts_c.get("error", 0),
        "timeout": status_counts_c.get("timeout", 0),
    }
    error_type_counts = {k: error_type_counts_c.get(k, 0) for k in ERROR_TYPE_KEYS}

    # benchmark 単位集計は npm_success (いずれかの経路で Node 実行可能) で判定
    bench_flags: dict[str, list[bool]] = defaultdict(list)
    for t in tags_out:
        bench_flags[t["slug_id"]].append(bool(t["npm_success"]))
    benchmarks_all_success = sum(1 for flags in bench_flags.values() if flags and all(flags))
    benchmarks_partial = sum(1 for flags in bench_flags.values() if flags and any(flags) and not all(flags))
    benchmarks_all_failed = sum(1 for flags in bench_flags.values() if flags and not any(flags))

    per_library_involvement: dict[str, dict[str, int]] = defaultdict(lambda: {"attempted": 0, "success": 0})
    for r in results:
        for pkg in r["libraries"]:
            per_library_involvement[pkg]["attempted"] += 1
            if r["status"] == "success":
                per_library_involvement[pkg]["success"] += 1

    per_libcount_stats: dict[int, dict[str, int]] = defaultdict(lambda: {"attempted": 0, "success": 0})
    for r in results:
        n: int = int(r["n_libraries"])
        per_libcount_stats[n]["attempted"] += 1
        if r["status"] == "success":
            per_libcount_stats[n]["success"] += 1

    step2_success_pairs: set[tuple[str, int]] = {(r["slug_id"], r["test_idx"]) for r in step2_tags if r.get("node_success", False)}
    step3_success_pairs: set[tuple[str, int]] = {k for k, s in step3_result_map.items() if s == "success"}
    newly_successful: int = sum(1 for k in step3_success_pairs if k not in step2_success_pairs)
    newly_broken: int = sum(1 for k in step3_result_map if k in step2_success_pairs and k not in step3_success_pairs)

    summary = {
        "elapsed_sec": elapsed_sec,
        "max_workers": args.max_workers,
        "libraries_defined": len(resolver),
        "step2_totals_per_test": {
            "total": len(step2_tags),
            "success": n_step2_success,
            "failed": len(step2_tags) - n_step2_success,
        },
        "target_benchmarks": len(target_slug_ids),
        "skipped_bench_no_meta": skipped_bench_no_meta,
        "skipped_bench_no_lib": skipped_bench_no_lib,
        "injected_benchmarks": injected_bench_count,
        "injected_programs": len(jobs),
        "libs_per_benchmark_distribution": dict(sorted(lib_count_dist.items())),
        "status_counts": status_counts,
        "error_type_counts": error_type_counts,
        "newly_successful": newly_successful,
        "newly_broken": newly_broken,
        "node_success_total": sum(1 for t in tags_out if t["node_success"]),
        "npm_success_total": sum(1 for t in tags_out if t["npm_success"]),
        "node_or_npm_success_total": sum(1 for t in tags_out if t["node_success"] or t["npm_success"]),
        "benchmark_summary": {
            "benchmarks_total": len(bench_flags),
            "benchmarks_all_success": benchmarks_all_success,
            "benchmarks_partial_success": benchmarks_partial,
            "benchmarks_all_failed": benchmarks_all_failed,
        },
        "success_rate_by_libcount": {
            str(n): {
                "attempted": v["attempted"],
                "success": v["success"],
                "rate": round(v["success"] / v["attempted"], 4) if v["attempted"] else 0.0,
            }
            for n, v in sorted(per_libcount_stats.items())
        },
        "library_involvement": dict(sorted(per_library_involvement.items(), key=lambda kv: -kv[1]["success"])),
    }
    hayalab.write_json(STEP3_OUT / "summary.json", summary)

    # --- Section 9: 進捗レポート ---
    print(f"[step3] elapsed: {elapsed_sec:.1f}s")
    print(f"[step3] status_counts: {status_counts}")
    print(f"[step3] error_type_counts: {error_type_counts}")
    print(f"[step3] newly_successful (step2 fail → step3 success): {newly_successful}")
    print(f"[step3] newly_broken     (step2 success → step3 fail): {newly_broken}")
    print(f"[step3] node_success_total: {summary['node_success_total']}")
    print(f"[step3] npm_success_total:  {summary['npm_success_total']}")
    print(f"[step3] node_or_npm_success_total: {summary['node_or_npm_success_total']}")
    print(f"[step3] benchmark_summary: {summary['benchmark_summary']}")
    print(f"[step3] success rate by libcount: {summary['success_rate_by_libcount']}")
    print(f"[step3] outputs: {STEP3_OUT}")
