"""実行時間ペアに元プログラムのソースコードを紐付ける.

`pairs.jsonl` の各ペアについて、計測ハーネスへ埋め込む前の元プログラム
(step6 と同じ振り分けで選ばれる step1 素版 / step3 require 注入版) を読み出し、
slow / fast のコードを対にした JSON を書き出す。

振り分けは step6 と同一:
- 全 test が node_success → step1 の program_<i>.js
- 全 test が npm_success → step3 の program_<i>.js (require ブロック注入済み)
- 全 test が playwright_success → step1 の program_<i>.js (page_html.html はペア間で共通)

入力:
- `outputs/jsperf/pair/time/<env>/pairs.jsonl`
- `outputs/jsperf/setup/step4/tags.jsonl`
- `outputs/jsperf/setup/step1/benchmark/<slug_id>/(program_<i>.js, page_html.html)`
- `outputs/jsperf/setup/step3/benchmark/<slug_id>/program_<i>.js` (npm 振り分け時のみ)

出力: `outputs/jsperf/pair/time/<env>/pair_programs.json`
(slug_id, html, slow{test_id, code}, fast{test_id, code}, mean_ratio のリスト)
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import hayalab
from hayalab.config import PathConfig


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


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数・パス解決 ---
    parser = argparse.ArgumentParser(description="実行時間ペアに元プログラムのコードを紐付ける.")
    parser.add_argument("--env", choices=["Node", "Playwright"], default="Node")
    args = parser.parse_args()

    CONFIG = PathConfig()
    SETUP_ROOT: Path = CONFIG.outputs / "jsperf" / "setup"
    STEP1_BENCH: Path = SETUP_ROOT / "step1" / "benchmark"
    STEP3_BENCH: Path = SETUP_ROOT / "step3" / "benchmark"
    STEP4_TAGS: Path = SETUP_ROOT / "step4" / "tags.jsonl"
    pair_dir: Path = CONFIG.outputs / "jsperf" / "pair" / "time" / args.env
    pairs_path: Path = pair_dir / "pairs.jsonl"

    for p in (pairs_path, STEP4_TAGS, STEP1_BENCH):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")

    # --- Section 2: 振り分けの再計算 ---
    bench_tags: dict[str, list[dict]] = defaultdict(list)
    for t in hayalab.read_jsonl(STEP4_TAGS):
        bench_tags[t["slug_id"]].append(t)
    env_by_slug: dict[str, str] = {}
    for slug_id, tests in bench_tags.items():
        env = _dispatch_env(tests)
        if env is not None:
            env_by_slug[slug_id] = env

    # --- Section 3: ペアごとのコード読み出し ---
    pairs = hayalab.read_jsonl(pairs_path)
    code_cache: dict[tuple[str, int], str] = {}
    html_cache: dict[str, str] = {}
    entries: list[dict] = []
    skipped_no_env = 0
    skipped_missing_program = 0

    for pair in pairs:
        slug_id = pair["slug_id"]
        env = env_by_slug.get(slug_id)
        if env is None:
            skipped_no_env += 1
            continue
        codes: dict[str, str] = {}
        for side, idx in (("slow", pair["slow_test_idx"]), ("fast", pair["fast_test_idx"])):
            key = (slug_id, idx)
            if key not in code_cache:
                path = _program_path(STEP1_BENCH, STEP3_BENCH, slug_id, idx, env)
                if not path.exists():
                    break
                code_cache[key] = path.read_text(encoding="utf-8")
            codes[side] = code_cache[key]
        if len(codes) < 2:
            skipped_missing_program += 1
            continue
        if slug_id not in html_cache:
            html_path = STEP1_BENCH / slug_id / "page_html.html"
            html_cache[slug_id] = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
        entries.append(
            {
                "slug_id": slug_id,
                "html": html_cache[slug_id],
                "slow": {"test_id": pair["slow_test_idx"], "code": hayalab.code_clean(codes["slow"])},
                "fast": {"test_id": pair["fast_test_idx"], "code": hayalab.code_clean(codes["fast"])},
                "mean_ratio": pair["mean_ratio"],
            }
        )

    # --- Section 4: 出力 ---
    out_path = pair_dir / "pair_programs.json"
    hayalab.write_json(out_path, entries)
    print(f"[pair] {args.env}: pairs={len(entries)}/{len(pairs)} (no_env={skipped_no_env} missing_program={skipped_missing_program}) -> {out_path}")
