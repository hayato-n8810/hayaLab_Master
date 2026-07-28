"""Step 5: ベンチマーク単位の計測環境振り分け.

Step 4 までの成功タグ (node_success / npm_success / playwright_success) をもとに、
各ベンチマークを計測環境へ振り分け、実行環境ごとに統一したプログラムを配置する。

振り分けルール:
1. どの環境の成功タグも付かない test を除外する。
2. 除外後に残った test が 2 未満のベンチマークは除外する (ペア不成立)。
3. 残った test 全体が同一環境で成功しているベンチマークを、その環境へ振り分ける
   (上から順に判定。プログラムのソースはベンチマーク内で統一される):
   - 全 test が node_success → Node 計測 (dispatch_rule = "node"、step1 の素版 program)
   - 全 test が npm_success → Node 計測 (dispatch_rule = "npm"、step3 の require 注入版 program)
   - 全 test が playwright_success → Playwright 計測 (dispatch_rule = "playwright"、
     step1 の素版 program + page_html.html)
4. いずれの環境でも「全 test 成功」にならない (環境が混在する) ベンチマークは除外する。

配置: 計測対象ベンチマークの program を実行環境ごとに以下へコピーする。
- Node (dispatch_rule = "node" / "npm"): `data/jsPerf/Node/<slug_id>/program_<i>.js`
- Playwright: `data/jsPerf/Playwright/<slug_id>/(program_<i>.js, page_html.html)`

入力:
- `outputs/jsperf/setup/step4/tags.jsonl` (全ベンチマークの成功タグ)
- `outputs/jsperf/setup/step1/benchmark/<slug_id>/(program_<i>.js, page_html.html)`
- `outputs/jsperf/setup/step3/benchmark/<slug_id>/program_<i>.js`

出力:
- `data/jsPerf/Node/<slug_id>/`, `data/jsPerf/Playwright/<slug_id>/`: 計測用プログラム実体
- `outputs/jsperf/setup/step5/node_bench.jsonl`: Node 計測対象 (per-bench、配置パス付き)
- `outputs/jsperf/setup/step5/playwright_bench.jsonl`: Playwright 計測対象 (同上)
- `outputs/jsperf/setup/step5/excluded_js.jsonl`: 除外された test と理由
- `outputs/jsperf/setup/step5/excluded_benchmarks.jsonl`: 除外ベンチマークと理由
- `outputs/jsperf/setup/step5/summary.json`: 件数集計
"""

from __future__ import annotations

import shutil
from collections import Counter, defaultdict
from pathlib import Path

import hayalab
from hayalab.config import PathConfig

# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    CONFIG = PathConfig()
    REPO_ROOT: Path = CONFIG.root
    SETUP_ROOT: Path = CONFIG.outputs / "jsperf" / "setup"
    STEP1_BENCH: Path = SETUP_ROOT / "step1" / "benchmark"
    STEP3_BENCH: Path = SETUP_ROOT / "step3" / "benchmark"
    STEP4_TAGS: Path = SETUP_ROOT / "step4" / "tags.jsonl"
    STEP5_OUT: Path = SETUP_ROOT / "step5"
    STEP5_OUT.mkdir(parents=True, exist_ok=True)

    JSPERF_ROOT: Path = CONFIG.data / "jsPerf"
    NODE_DST_ROOT: Path = JSPERF_ROOT / "Node" / "origin"
    PW_DST_ROOT: Path = JSPERF_ROOT / "Playwright" / "origin"

    for p in (STEP1_BENCH, STEP4_TAGS):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")

    # 冪等性のため配置先を作り直す (前回の残骸を残さない)
    for d in (NODE_DST_ROOT, PW_DST_ROOT):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    # --- Section 2: タグ読み込み ---
    tags: list[dict] = hayalab.read_jsonl(STEP4_TAGS)
    bench_tags: dict[str, list[dict]] = defaultdict(list)
    for t in tags:
        bench_tags[t["slug_id"]].append(t)
    print(f"[step5] benchmarks total: {len(bench_tags)}  tests total: {len(tags)}")

    # --- Section 3: ベンチマーク単位の振り分け + プログラム配置 ---
    node_benches: list[dict] = []
    pw_benches: list[dict] = []
    excluded_js: list[dict] = []
    excluded_benches: list[dict] = []

    for slug_id in sorted(bench_tags):
        tests = sorted(bench_tags[slug_id], key=lambda r: r["test_idx"])
        slug = tests[0]["slug"]

        # 無タグ test を除外し、残った test で環境を判定する
        kept = [t for t in tests if t["node_success"] or t["npm_success"] or t["playwright_success"]]
        for t in tests:
            if t not in kept:
                excluded_js.append({"slug_id": slug_id, "slug": slug, "test_idx": t["test_idx"], "reason": "no_success_tag"})

        if len(kept) < 2:
            excluded_benches.append({"slug_id": slug_id, "slug": slug, "n_tests": len(tests), "n_kept": len(kept), "reason": "insufficient_pair"})
            for t in kept:
                excluded_js.append({"slug_id": slug_id, "slug": slug, "test_idx": t["test_idx"], "reason": "benchmark_excluded"})
            continue

        if all(t["node_success"] for t in kept):
            env, rule, bench_src = "node", "node", STEP1_BENCH
        elif all(t["npm_success"] for t in kept):
            env, rule, bench_src = "node", "npm", STEP3_BENCH
        elif all(t["playwright_success"] for t in kept):
            env, rule, bench_src = "playwright", "playwright", STEP1_BENCH
        else:
            excluded_benches.append({"slug_id": slug_id, "slug": slug, "n_tests": len(tests), "n_kept": len(kept), "reason": "mixed_env"})
            for t in kept:
                excluded_js.append({"slug_id": slug_id, "slug": slug, "test_idx": t["test_idx"], "reason": "mixed_env"})
            continue

        # 配置先 (実行環境ごとに統一したソースからコピー; ファイル欠損は除外して記録)
        dst_root = NODE_DST_ROOT if env == "node" else PW_DST_ROOT
        dst_dir = dst_root / slug_id
        dst_dir.mkdir(parents=True, exist_ok=True)
        tests_out: list[dict] = []
        for t in kept:
            src_program = bench_src / slug_id / f"program_{t['test_idx']}.js"
            if not src_program.exists():
                excluded_js.append({"slug_id": slug_id, "slug": slug, "test_idx": t["test_idx"], "reason": "missing_program_file"})
                continue
            dst_program = dst_dir / f"program_{t['test_idx']}.js"
            shutil.copy2(src_program, dst_program)
            tests_out.append({"test_idx": t["test_idx"], "program": dst_program.relative_to(REPO_ROOT).as_posix()})

        if len(tests_out) < 2:
            shutil.rmtree(dst_dir)
            excluded_benches.append({"slug_id": slug_id, "slug": slug, "n_tests": len(tests), "n_kept": len(kept), "reason": "programs_missing"})
            continue

        record = {"slug_id": slug_id, "slug": slug, "env": env, "dispatch_rule": rule, "tests": tests_out}
        if env == "playwright":
            src_page = STEP1_BENCH / slug_id / "page_html.html"
            if src_page.exists():
                dst_page = dst_dir / "page_html.html"
                shutil.copy2(src_page, dst_page)
                record["page_html"] = dst_page.relative_to(REPO_ROOT).as_posix()
            else:
                record["page_html"] = None
            pw_benches.append(record)
        else:
            node_benches.append(record)

    # --- Section 4: 出力書き出し ---
    hayalab.write_jsonl(STEP5_OUT / "node_bench.jsonl", node_benches)
    hayalab.write_jsonl(STEP5_OUT / "playwright_bench.jsonl", pw_benches)
    excluded_js.sort(key=lambda x: (x["slug_id"], x["test_idx"]))
    hayalab.write_jsonl(STEP5_OUT / "excluded_js.jsonl", excluded_js)
    hayalab.write_jsonl(STEP5_OUT / "excluded_benchmarks.jsonl", excluded_benches)

    # --- Section 5: 集計 (summary.json) ---
    rule_counts = Counter(r["dispatch_rule"] for r in node_benches + pw_benches)
    excluded_js_reasons = Counter(r["reason"] for r in excluded_js)
    excluded_bench_reasons = Counter(r["reason"] for r in excluded_benches)
    test_hist = Counter(len(r["tests"]) for r in node_benches + pw_benches)

    summary = {
        "benchmarks_total": len(bench_tags),
        "node_benchmarks": len(node_benches),
        "playwright_benchmarks": len(pw_benches),
        "excluded_benchmarks": len(excluded_benches),
        "dispatch_rule_counts": dict(sorted(rule_counts.items())),
        "measured_tests_node": sum(len(r["tests"]) for r in node_benches),
        "measured_tests_playwright": sum(len(r["tests"]) for r in pw_benches),
        "excluded_js_total": len(excluded_js),
        "excluded_js_reasons": dict(sorted(excluded_js_reasons.items())),
        "excluded_benchmark_reasons": dict(sorted(excluded_bench_reasons.items())),
        "measured_test_count_hist": {str(k): v for k, v in sorted(test_hist.items())},
    }
    hayalab.write_json(STEP5_OUT / "summary.json", summary)

    # --- Section 6: 進捗レポート ---
    print(f"[step5] node benchmarks:       {len(node_benches)}  (rules: {dict(sorted(rule_counts.items()))})")
    print(f"[step5] playwright benchmarks: {len(pw_benches)}")
    print(f"[step5] excluded benchmarks:   {len(excluded_benches)}  ({dict(sorted(excluded_bench_reasons.items()))})")
    print(f"[step5] excluded js:           {len(excluded_js)}  ({dict(sorted(excluded_js_reasons.items()))})")
    print(f"[step5] programs placed: {NODE_DST_ROOT}  /  {PW_DST_ROOT}")
    print(f"[step5] metadata outputs: {STEP5_OUT}")
