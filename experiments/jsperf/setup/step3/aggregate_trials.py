"""Step3 trial 結果の横断集約スクリプト.

`outputs/jsperf/setup/step3/trials/<library>/results.jsonl` を全ライブラリ分読み込み、
どの program がどのライブラリインポートで成功したかを追跡可能な形に集計する.

出力: `outputs/jsperf/setup/step3/aggregate/`
- `program_success.jsonl`: program 単位で trials_attempted / trials_succeeded を記録
- `library_effectiveness.json`: library 単位で成功数・unique win 数などを記録
- `benchmark_coverage.jsonl`: benchmark 単位で解決状況を記録
- `summary.json`: 全体サマリ
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import hayalab
from hayalab.config import PathConfig


# --- Helpers (関数化: 複数箇所または per-record 処理) -----------------
def _write_jsonl(path: Path, records: list[dict]) -> None:
    """レコード列を JSONL として書き出す (順序保存)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _load_jsonl(path: Path) -> list[dict]:
    """JSONL ファイルをレコードのリストとして読み込む."""
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    CONFIG = PathConfig()
    STEP1_DIR: Path = CONFIG.outputs / "jsperf" / "setup" / "step1"
    STEP2_TAGS: Path = CONFIG.outputs / "jsperf" / "setup" / "step2" / "tags.jsonl"
    TRIALS_DIR: Path = CONFIG.outputs / "jsperf" / "setup" / "step3" / "trials"
    AGG_DIR: Path = CONFIG.outputs / "jsperf" / "setup" / "step3" / "aggregate"
    AGG_DIR.mkdir(parents=True, exist_ok=True)

    if not STEP2_TAGS.exists():
        raise SystemExit(f"missing input: {STEP2_TAGS}")
    if not TRIALS_DIR.exists():
        raise SystemExit(f"missing input: {TRIALS_DIR}")

    # --- Section 2: step2 タグ読み込み ---
    step2_tags: list[dict] = _load_jsonl(STEP2_TAGS)
    step2_success_pairs: set[tuple[str, int]] = {(r["slug_id"], r["test_idx"]) for r in step2_tags if r.get("node_success", False)}
    step2_failed_pairs: set[tuple[str, int]] = {(r["slug_id"], r["test_idx"]) for r in step2_tags if not r.get("node_success", False)}
    slug_map: dict[str, str] = {r["slug_id"]: r["slug"] for r in step2_tags}
    print(f"[aggregate] step2 total: {len(step2_tags)}")
    print(f"[aggregate] step2 success: {len(step2_success_pairs)}")
    print(f"[aggregate] step2 failed:  {len(step2_failed_pairs)}")

    # --- Section 3: 全 trial の results.jsonl を読み込む ---
    trial_libraries: list[str] = sorted([p.name for p in TRIALS_DIR.iterdir() if (p / "results.jsonl").exists()])
    print(f"[aggregate] trial libraries: {len(trial_libraries)}")
    print(f"[aggregate] libraries: {', '.join(trial_libraries)}")

    per_program_attempts: dict[tuple[str, int], list[str]] = defaultdict(list)
    per_program_success: dict[tuple[str, int], list[str]] = defaultdict(list)
    per_library_counts: dict[str, dict[str, int]] = {}
    per_library_records: dict[str, list[dict]] = {}

    for lib in trial_libraries:
        recs: list[dict] = _load_jsonl(TRIALS_DIR / lib / "results.jsonl")
        per_library_records[lib] = recs
        per_library_counts[lib] = {
            "attempted": len(recs),
            "success": 0,
            "error": 0,
            "timeout": 0,
        }
        for r in recs:
            key: tuple[str, int] = (r["slug_id"], r["test_idx"])
            per_program_attempts[key].append(lib)
            status: str = r.get("status", "error")
            if status == "success":
                per_program_success[key].append(lib)
                per_library_counts[lib]["success"] += 1
            elif status == "timeout":
                per_library_counts[lib]["timeout"] += 1
            else:
                per_library_counts[lib]["error"] += 1

    # --- Section 4: program 単位の集計 (program_success.jsonl) ---
    program_records: list[dict] = []
    for key in sorted(per_program_attempts.keys()):
        slug_id, test_idx = key
        attempts: list[str] = sorted(per_program_attempts[key])
        successes: list[str] = sorted(per_program_success.get(key, []))
        program_records.append(
            {
                "slug_id": slug_id,
                "slug": slug_map.get(slug_id, ""),
                "test_idx": test_idx,
                "step2_success": key in step2_success_pairs,
                "trials_attempted": attempts,
                "trials_succeeded": successes,
                "resolved_in_step3": len(successes) > 0,
            }
        )
    _write_jsonl(AGG_DIR / "program_success.jsonl", program_records)

    resolved_in_step3_set: set[tuple[str, int]] = {(r["slug_id"], r["test_idx"]) for r in program_records if r["resolved_in_step3"]}
    print(f"[aggregate] programs attempted in step3: {len(program_records)}")
    print(f"[aggregate] programs resolved in step3:  {len(resolved_in_step3_set)}")

    # --- Section 5: library 単位の集計 (library_effectiveness.json) ---
    # unique_win = そのライブラリでのみ成功した program 数
    library_effectiveness: dict[str, dict] = {}
    for lib in trial_libraries:
        succeeded_pairs: set[tuple[str, int]] = {(r["slug_id"], r["test_idx"]) for r in per_library_records[lib] if r.get("status") == "success"}
        unique_win: int = sum(1 for pair in succeeded_pairs if per_program_success.get(pair, []) == [lib])
        matched_bench_ids: set[str] = {r["slug_id"] for r in per_library_records[lib]}
        bench_success_flags: dict[str, list[bool]] = defaultdict(list)
        for r in per_library_records[lib]:
            bench_success_flags[r["slug_id"]].append(r.get("status") == "success")
        bench_all_success = sum(1 for flags in bench_success_flags.values() if flags and all(flags))
        bench_partial = sum(1 for flags in bench_success_flags.values() if flags and any(flags) and not all(flags))
        bench_all_failed = sum(1 for flags in bench_success_flags.values() if flags and not any(flags))

        counts = per_library_counts[lib]
        succeeded_count: int = counts["success"]
        attempted_count: int = counts["attempted"]
        library_effectiveness[lib] = {
            "programs_attempted": attempted_count,
            "programs_succeeded": succeeded_count,
            "programs_error": counts["error"],
            "programs_timeout": counts["timeout"],
            "success_rate": round(succeeded_count / attempted_count, 4) if attempted_count else 0.0,
            "programs_unique_win": unique_win,
            "matched_benchmarks": len(matched_bench_ids),
            "benchmarks_all_success": bench_all_success,
            "benchmarks_partial_success": bench_partial,
            "benchmarks_all_failed": bench_all_failed,
        }

    library_effectiveness_sorted: dict[str, dict] = dict(
        sorted(
            library_effectiveness.items(),
            key=lambda kv: -kv[1]["programs_succeeded"],
        )
    )
    hayalab.write_json(AGG_DIR / "library_effectiveness.json", library_effectiveness_sorted)

    # --- Section 6: benchmark 単位の集計 (benchmark_coverage.jsonl) ---
    bench_test_counts: dict[str, int] = {}
    for meta_path in sorted(STEP1_DIR.glob("*/meta.json")):
        meta = hayalab.read_json(meta_path)
        bench_test_counts[meta["slug_id"]] = int(meta["test_count"])

    bench_program_pairs: dict[str, list[tuple[int, bool]]] = defaultdict(list)
    for r in step2_tags:
        sid: str = r["slug_id"]
        tid: int = r["test_idx"]
        step2_ok: bool = r.get("node_success", False)
        step3_ok: bool = (sid, tid) in resolved_in_step3_set
        bench_program_pairs[sid].append((tid, step2_ok or step3_ok))

    benchmark_records: list[dict] = []
    for sid in sorted(bench_program_pairs.keys()):
        flags = [(tid, ok) for tid, ok in bench_program_pairs[sid]]
        ok_count: int = sum(1 for _, ok in flags if ok)
        fail_count: int = len(flags) - ok_count
        step2_ok_count: int = sum(1 for tid, _ok in flags if (sid, tid) in step2_success_pairs)
        step3_ok_count: int = sum(1 for tid, _ok in flags if (sid, tid) in resolved_in_step3_set)
        benchmark_records.append(
            {
                "slug_id": sid,
                "slug": slug_map.get(sid, ""),
                "test_count": bench_test_counts.get(sid, len(flags)),
                "step2_success_count": step2_ok_count,
                "step3_resolved_count": step3_ok_count,
                "total_resolved_count": ok_count,
                "still_failing_count": fail_count,
                "all_resolved": fail_count == 0,
            }
        )
    _write_jsonl(AGG_DIR / "benchmark_coverage.jsonl", benchmark_records)

    # --- Section 7: 全体サマリ ---
    overlap_hist: Counter[int] = Counter(len(succs) for succs in per_program_success.values())
    library_hits_hist: dict[int, int] = dict(sorted(overlap_hist.items()))

    all_resolved_benchmarks: int = sum(1 for r in benchmark_records if r["all_resolved"])
    still_partial_benchmarks: int = sum(1 for r in benchmark_records if not r["all_resolved"] and r["total_resolved_count"] > 0)
    still_all_failed_benchmarks: int = sum(1 for r in benchmark_records if r["total_resolved_count"] == 0)

    summary: dict = {
        "trial_libraries_count": len(trial_libraries),
        "step2_totals": {
            "total": len(step2_tags),
            "success": len(step2_success_pairs),
            "failed": len(step2_failed_pairs),
        },
        "step3_program_totals": {
            "attempted": len(program_records),
            "resolved": len(resolved_in_step3_set),
            "still_failing": len(step2_failed_pairs) - len(resolved_in_step3_set),
        },
        "library_hits_histogram": library_hits_hist,
        "benchmark_totals": {
            "total": len(benchmark_records),
            "all_resolved": all_resolved_benchmarks,
            "partial_resolved": still_partial_benchmarks,
            "all_failed": still_all_failed_benchmarks,
        },
        "top_libraries_by_success": [{"library": lib, "programs_succeeded": info["programs_succeeded"]} for lib, info in list(library_effectiveness_sorted.items())[:10]],
    }
    hayalab.write_json(AGG_DIR / "summary.json", summary)

    # --- Section 8: 進捗レポート ---
    print("[aggregate] === Summary ===")
    print(f"  trial libraries: {summary['trial_libraries_count']}")
    print(f"  step2 success: {summary['step2_totals']['success']}")
    print(f"  step3 resolved: {summary['step3_program_totals']['resolved']}")
    print(f"  step3 still failing: {summary['step3_program_totals']['still_failing']}")
    print(f"  library_hits_histogram: {summary['library_hits_histogram']}")
    print(f"  benchmarks all_resolved: {summary['benchmark_totals']['all_resolved']}")
    print(f"  benchmarks partial: {summary['benchmark_totals']['partial_resolved']}")
    print(f"  benchmarks all_failed: {summary['benchmark_totals']['all_failed']}")
    print()
    print("  top libraries by programs_succeeded:")
    for entry in summary["top_libraries_by_success"]:
        print(f"    {entry['library']:22s} {entry['programs_succeeded']}")
    print(f"[aggregate] outputs: {AGG_DIR}")
