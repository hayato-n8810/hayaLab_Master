"""計測結果から実行時間に差のあるプログラムペアを作成する.

`outputs/jsperf/measure/<env>/results.jsonl` の success レコードについて、
test ごとに samples_ns の平均の信頼区間を算出し、同一 slug_id 内で信頼区間が
一切重複しない test の組をペアとして書き出す。 Playwright の samples_ms は
分解能 5 µs 刻みの ns に丸めてから扱う。

加えて、信頼区間の重複有無を問わない同一 slug_id 内の全 test ペアについて、
slow / fast の区別を付けずに元プログラムのコードを対にした JSON を書き出す。
元プログラムの振り分けは step6 と同一:
- 全 test が node_success → step1 の program_<i>.js
- 全 test が npm_success → step3 の program_<i>.js (require ブロック注入済み)
- 全 test が playwright_success → step1 の program_<i>.js (page_html.html はペア間で共通)

入力:
- `outputs/jsperf/measure/<env>/results.jsonl`
- `outputs/jsperf/setup/step4/tags.jsonl`
- `outputs/jsperf/setup/step1/benchmark/<slug_id>/(program_<i>.js, page_html.html)`
- `outputs/jsperf/setup/step3/benchmark/<slug_id>/program_<i>.js` (npm 振り分け時のみ)

出力: `outputs/jsperf/pair/time/<env>/`
- `intervals.jsonl` : test ごとの (平均, 信頼区間) (slug_id, test_idx) ソート
- `pairs.jsonl`     : 信頼区間が重複しない test ペア (slug_id, fast_test_idx, slow_test_idx) ソート
- `summary.json`    : 対象ベンチマーク / test 数とペア数の集計
- `all_pair_programs.json` : 全 test ペアの (slug_id, html, programs[{test_id, code}, {test_id, code}]) のリスト。
  programs は test_id 昇順、リストは (slug_id, programs[0].test_id, programs[1].test_id) ソート
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
from pathlib import Path

import hayalab
from hayalab.config import PathConfig
from hayalab.config.jsperf_config import CONFIDENCE
from hayalab.jsperf.interval import disjoint_interval_pairs, mean_confidence_interval

# --- Constants (ファイル先頭で調整するハイパーパラメータ) ----------
PLAYWRIGHT_RESOLUTION_NS: int = 5_000  # performance.now() の分解能 (crossOriginIsolated 時 5 µs)
DEFAULT_MAX_WORKERS: int = 8
CHUNK_SIZE: int = 64


# --- Helpers (per-benchmark / per-test 処理) ------------------------
def _dispatch_env(tests: list[dict]) -> str | None:
    """step4 のタグからベンチマークの計測環境を再計算する.

    Args:
        tests: 同一 slug_id の tags.jsonl レコード群.

    Returns:
        "node" / "npm" / "playwright"。 ペア不成立または環境混在なら None.
    """
    kept = [t for t in tests if t["node_success"] or t["npm_success"] or t["playwright_success"]]
    if len(kept) < 2:
        return None
    if all(t["node_success"] for t in kept):
        return "node"
    if all(t["npm_success"] for t in kept):
        return "npm"
    if all(t["playwright_success"] for t in kept):
        return "playwright"
    return None


def _program_path(step1_bench: Path, step3_bench: Path, slug_id: str, test_idx: int, env: str) -> Path:
    """計測対象となった元プログラムのパスを返す.

    Args:
        step1_bench: step1 の benchmark ディレクトリ.
        step3_bench: step3 の benchmark ディレクトリ.
        slug_id: ベンチマークの slug_id.
        test_idx: test のインデックス.
        env: _dispatch_env が返す計測環境.

    Returns:
        program_<test_idx>.js のパス.
    """
    root = step3_bench if env == "npm" else step1_bench
    return root / slug_id / f"program_{test_idx}.js"


def _load_program(path: Path) -> str | None:
    """元プログラムを読み出して整形する (ProcessPoolExecutor のワーカー).

    Args:
        path: program_<i>.js のパス.

    Returns:
        code_clean 適用後のコード。 ファイルが存在しなければ None.
    """
    if not path.exists():
        return None
    return hayalab.code_clean(path.read_text(encoding="utf-8"))


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数・パス解決 ---
    parser = argparse.ArgumentParser(description="信頼区間が重複しない実行時間ペアを作成する.")
    parser.add_argument("--env", choices=["Node", "Playwright"], default="Node")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    args = parser.parse_args()

    CONFIG = PathConfig()
    results_path: Path = CONFIG.outputs / "jsperf" / "measure" / args.env / "results.jsonl"
    out_dir: Path = CONFIG.outputs / "jsperf" / "pair" / "time" / args.env
    SETUP_ROOT: Path = CONFIG.outputs / "jsperf" / "setup"
    STEP1_BENCH: Path = SETUP_ROOT / "step1" / "benchmark"
    STEP3_BENCH: Path = SETUP_ROOT / "step3" / "benchmark"
    STEP4_TAGS: Path = SETUP_ROOT / "step4" / "tags.jsonl"
    if not results_path.exists():
        raise SystemExit(f"results not found: {results_path}")
    for p in (STEP4_TAGS, STEP1_BENCH):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Section 2: success レコードの信頼区間算出 ---
    records = hayalab.read_jsonl(results_path)
    intervals: list[dict] = []
    for record in records:
        if args.env == "Playwright":
            # Playwright は ms 単位のため ns に変換し、分解能 (5 µs) 未満の浮動小数誤差を丸めで除去する
            samples = [round(s * 1_000_000 / PLAYWRIGHT_RESOLUTION_NS) * PLAYWRIGHT_RESOLUTION_NS for s in record.get("samples_ms") or []]
        else:
            samples = record.get("samples_ns") or []
        if record.get("status") != "success" or len(samples) < 2:
            continue
        mean, ci_low, ci_high = mean_confidence_interval(samples, CONFIDENCE)
        intervals.append(
            {
                "slug_id": record["slug_id"],
                "test_idx": record["test_idx"],
                "n": len(samples),
                "mean_ns": mean,
                "ci_low_ns": ci_low,
                "ci_high_ns": ci_high,
            }
        )
    intervals.sort(key=lambda r: (r["slug_id"], r["test_idx"]))
    hayalab.write_jsonl(out_dir / "intervals.jsonl", intervals)

    # --- Section 3: slug_id 単位で信頼区間が重複しない組を抽出 ---
    by_slug: dict[str, dict[int, dict]] = defaultdict(dict)
    for stat in intervals:
        by_slug[stat["slug_id"]][stat["test_idx"]] = stat

    pairs: list[dict] = []
    all_pairs: list[tuple[str, int, int]] = []  # 信頼区間の重複有無を問わない全 test ペア
    target_slugs = 0  # 信頼区間を算出できた test が 2 つ以上あるベンチマーク数
    target_tests = 0  # 上記ベンチマークに属する test 数
    total_pairs = 0  # 上記ベンチマーク内で組める test ペアの総数
    for slug_id in sorted(by_slug):
        stats_by_test = by_slug[slug_id]
        if len(stats_by_test) < 2:
            continue
        target_slugs += 1
        target_tests += len(stats_by_test)
        total_pairs += len(stats_by_test) * (len(stats_by_test) - 1) // 2
        all_pairs.extend((slug_id, a, b) for a, b in combinations(sorted(stats_by_test), 2))
        bounds = {idx: (s["ci_low_ns"], s["ci_high_ns"]) for idx, s in stats_by_test.items()}
        for fast_idx, slow_idx in disjoint_interval_pairs(bounds):
            fast, slow = stats_by_test[fast_idx], stats_by_test[slow_idx]
            pairs.append(
                {
                    "slug_id": slug_id,
                    "fast_test_idx": fast_idx,
                    "slow_test_idx": slow_idx,
                    "fast": {"n": fast["n"], "mean_ns": fast["mean_ns"]},
                    "slow": {"n": slow["n"], "mean_ns": slow["mean_ns"]},
                    "mean_ratio": slow["mean_ns"] / fast["mean_ns"],  # slowがfastの何倍遅いか
                }
            )
    pairs.sort(key=lambda p: (p["slug_id"], p["fast_test_idx"], p["slow_test_idx"]))
    hayalab.write_jsonl(out_dir / "pairs.jsonl", pairs)

    # --- Section 4: 集計の保存 ---
    summary = {
        "env": args.env,
        "confidence": CONFIDENCE,  # 信頼区間の信頼水準
        "total_slugs": len({r["slug_id"] for r in records}),  # 計測結果に含まれる全ベンチマーク数
        "total_tests": len(records),  # 計測結果に含まれる全 test 数
        "target_slugs": target_slugs,  # 比較対象となったベンチマーク数
        "target_tests": target_tests,  # 比較対象となった test 数
        "total_pairs": total_pairs,  # 比較対象ベンチマーク内で組める全 test ペア数
        "disjoint_pairs": len(pairs),  # 信頼区間が一切重複しない test ペア数
    }
    hayalab.write_json(out_dir / "summary.json", summary)
    print(f"[pair] {args.env}: slugs={target_slugs}/{summary['total_slugs']} tests={target_tests}/{len(records)} pairs={len(pairs)}/{total_pairs} -> {out_dir}")

    # --- Section 5: 振り分けの再計算 ---
    bench_tags: dict[str, list[dict]] = defaultdict(list)
    for t in hayalab.read_jsonl(STEP4_TAGS):
        bench_tags[t["slug_id"]].append(t)
    env_by_slug: dict[str, str] = {}
    for slug_id, tests in bench_tags.items():
        env = _dispatch_env(tests)
        if env is not None:
            env_by_slug[slug_id] = env

    # --- Section 6: 全 test ペアに含まれるプログラムの読み出しと整形 (並列) ---
    program_keys = sorted({(slug_id, idx) for slug_id, a, b in all_pairs if slug_id in env_by_slug for idx in (a, b)})
    program_paths = [_program_path(STEP1_BENCH, STEP3_BENCH, slug_id, idx, env_by_slug[slug_id]) for slug_id, idx in program_keys]
    with ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        code_by_key: dict[tuple[str, int], str | None] = dict(zip(program_keys, executor.map(_load_program, program_paths, chunksize=CHUNK_SIZE)))
    print(f"[pair-all] {args.env}: programs={sum(c is not None for c in code_by_key.values())}/{len(program_keys)}")

    # --- Section 7: 全 test ペアの組み立て ---
    html_cache: dict[str, str] = {}
    entries: list[dict] = []
    skipped_no_env = 0
    skipped_missing_program = 0

    for slug_id, idx_a, idx_b in all_pairs:
        if slug_id not in env_by_slug:
            skipped_no_env += 1
            continue
        if code_by_key[(slug_id, idx_a)] is None or code_by_key[(slug_id, idx_b)] is None:
            skipped_missing_program += 1
            continue
        programs = [{"test_id": idx, "code": code_by_key[(slug_id, idx)]} for idx in (idx_a, idx_b)]
        if slug_id not in html_cache:
            html_path = STEP1_BENCH / slug_id / "page_html.html"
            html_cache[slug_id] = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
        entries.append({"slug_id": slug_id, "html": html_cache[slug_id], "programs": programs})

    # --- Section 8: 全 test ペアのプログラム出力 ---
    all_out_path = out_dir / "all_pair_programs.json"
    hayalab.write_json(all_out_path, entries)
    print(f"[pair-all] {args.env}: pairs={len(entries)}/{len(all_pairs)} (no_env={skipped_no_env} missing_program={skipped_missing_program}) -> {all_out_path}")
