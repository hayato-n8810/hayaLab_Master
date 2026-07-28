"""Step 6: 実行時間計測のためのハーネス付きプログラム整形.

Step 4 の成功タグ (tags.jsonl) から Step 5 と同一の振り分けロジックを再計算し、各 test を
実行環境ごとに Step 1〜4 の整形方法に忠実な計測ハーネスへ整形して measure/ 配下へ配置する。

振り分け (Step 5 と同一。step6 内で tags.jsonl から再計算する):
1. どの環境の成功タグも付かない test を除外する。
2. 残った test が 2 未満のベンチマークは除外する (ペア不成立)。
3. 残った test 全体が同一環境で成功しているベンチマークを振り分ける:
   - 全 test が node_success → Node 計測 (step1 素版 program)
   - 全 test が npm_success → Node 計測 (step3 の require 注入版 program)
   - 全 test が playwright_success → Playwright 計測 (step1 素版 program + page_html.html)
4. いずれの環境でも全 test 成功にならない (混在) ベンチマークは除外する。

計測ハーネスの整形方法 (各実行環境の Step 1〜4 の実行形式に忠実):
- Node (node/npm): `node <file>` で top-level 実行する .js。program 本体 (step1 program) を
  `function _iteration_unit() { ... }` に直接埋め込み、warmup/計測ループで反復呼び出しする。
  npm の require ブロックは反復ユニットの外 (ループ外) に 1 度だけ置く。時間は
  process.hrtime.bigint() (ns)。結果は fs で bench_<i>.result.json へ直接書き出す
  (本体の stdout / console.log 出力と混ざらないよう stdout は使わない)。
- Playwright: Step 4 と同一の bench HTML。program を JS 文字列リテラル ('<' を Unicode
  エスケープ) として同期インライン埋め込みし `const _iteration_unit = new Function(src)` で
  コンパイルして反復呼び出しする (program 無改変)。時間は performance.now() * 1e6 (ns 換算。
  Step 4 と同じ crossOriginIsolated 環境で高精度)。結果は window.__result に格納し、実行
  フェーズが page.evaluate で回収する (ブラウザはファイルに直接書けないため)。

npm の require ブロックは step3 program (= require_block + step1 program) の末尾一致で分離する。

入力:
- `outputs/jsperf/setup/step4/tags.jsonl` (全ベンチマークの成功タグ)
- `outputs/jsperf/setup/step1/benchmark/<slug_id>/(program_<i>.js, page_html.html)`
- `outputs/jsperf/setup/step3/benchmark/<slug_id>/program_<i>.js` (npm 振り分け時のみ)

出力:
- `data/jsPerf/Node/measure/<slug_id>/bench_<i>.measure.js`
  (実行すると同ディレクトリの `bench_<i>.result.json` に計測結果を書き出す)
- `data/jsPerf/Playwright/measure/<slug_id>/bench_<i>.measure.html`
- `outputs/jsperf/setup/step6/summary.json`: 振り分け・整形件数の集計
"""

from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import hayalab
from hayalab.config import PathConfig

# --- Constants (計測ハイパーパラメータ) ----------------------------
K_WARMUP: int = 5  # ウォームアップラウンド数 (計測破棄)
N_BATCH: int = 1000  # 1 バッチの反復ユニット数
M_MEASURE: int = 10  # 本計測ラウンド数 (samples の要素数)


# --- Helpers (per-test 整形; 複数回呼び出し) ------------------------
def _extract_require_block(step3_text: str, step1_text: str) -> str | None:
    """step3 program (= require_block + step1 program) から require ブロックを分離する.

    Args:
        step3_text: step3 の require 注入済み program の中身.
        step1_text: 同一 test の step1 素版 program の中身.

    Returns:
        require ブロック文字列。step3 が step1 を末尾に含まない (想定外) 場合は None.
    """
    if step3_text.endswith(step1_text):
        return step3_text[: len(step3_text) - len(step1_text)]
    return None


def _build_node_measure(slug_id: str, test_idx: int, body: str, result_name: str, require_block: str = "") -> str:
    """Node 計測用ハーネス (.js) を生成する.

    program 本体を `function _iteration_unit()` に直接埋め込み (レキシカルスコープ)、
    require ブロックは反復ユニットの外に 1 度だけ置く。 非 strict (step2/3 の CommonJS
    モジュールスコープ実行と同じ) で評価する。 結果は fs で自身と同ディレクトリの
    result_name へ直接書き出す (本体の stdout / console.log と混ざらないため stdout 不使用)。

    Args:
        slug_id: ベンチマークの slug_id.
        test_idx: test のインデックス.
        body: program 本体 (step1 program の中身、無加工).
        result_name: 結果 JSON のファイル名 (ハーネスと同ディレクトリへ書き出す).
        require_block: npm の require ブロック (node 素版なら空文字).

    Returns:
        bench_<i>.measure.js の内容.
    """
    meta_literal = json.dumps({"slug_id": slug_id, "test_idx": test_idx})
    result_literal = json.dumps(result_name)
    prefix = require_block if require_block else ""
    return (
        "const __fs = require('fs');\n"
        "const __path = require('path');\n"
        f"const __result_path = __path.join(__dirname, {result_literal});\n"
        f"{prefix}"
        f"const K_WARMUP = {K_WARMUP};\n"
        f"const N_BATCH = {N_BATCH};\n"
        f"const M_MEASURE = {M_MEASURE};\n"
        f"const meta = {meta_literal};\n"
        "function _iteration_unit() {\n"
        f"{body}\n"
        "}\n"
        "for (let r = 0; r < K_WARMUP; r++) { for (let i = 0; i < N_BATCH; i++) _iteration_unit(); }\n"
        "const samples = [];\n"
        "for (let r = 0; r < M_MEASURE; r++) {\n"
        "  const t0 = process.hrtime.bigint();\n"
        "  for (let i = 0; i < N_BATCH; i++) _iteration_unit();\n"
        "  const t1 = process.hrtime.bigint();\n"
        "  samples.push(Number(t1 - t0));\n"
        "}\n"
        "__fs.writeFileSync(__result_path, JSON.stringify({ ...meta, batch: N_BATCH, warmup: K_WARMUP, rounds: M_MEASURE, samples }));\n"
    )


def _build_playwright_measure(slug_id: str, test_idx: int, page_html: str, program: str) -> str:
    """Playwright 計測用ハーネス (.html) を生成する.

    program は JS 文字列リテラル ('<' を Unicode エスケープ) として同期インライン埋め込みし
    `new Function(src)` でコンパイルする (Step 4 と同一、program 無改変)。

    Args:
        slug_id: ベンチマークの slug_id.
        test_idx: test のインデックス.
        page_html: page_html.html の内容 (無ければ空文字).
        program: program_<i>.js の中身 (無加工のソースコード).

    Returns:
        bench_<i>.measure.html の内容.
    """
    src_literal = json.dumps(program).replace("<", "\\u003c")
    meta_literal = json.dumps({"slug_id": slug_id, "test_idx": test_idx})
    harness = (
        "<script>\n"
        "(() => {\n"
        f"  const K_WARMUP = {K_WARMUP};\n"
        f"  const N_BATCH = {N_BATCH};\n"
        f"  const M_MEASURE = {M_MEASURE};\n"
        f"  const src = {src_literal};\n"
        f"  const out = {meta_literal};\n"
        "  try {\n"
        "    const _iteration_unit = new Function(src);\n"
        "    for (let r = 0; r < K_WARMUP; r++) { for (let i = 0; i < N_BATCH; i++) _iteration_unit(); }\n"
        "    const samples = [];\n"
        "    for (let r = 0; r < M_MEASURE; r++) {\n"
        "      const t0 = performance.now();\n"
        "      for (let i = 0; i < N_BATCH; i++) _iteration_unit();\n"
        "      const t1 = performance.now();\n"
        "      samples.push((t1 - t0) * 1e6);\n"
        "    }\n"
        "    out.batch = N_BATCH; out.warmup = K_WARMUP; out.rounds = M_MEASURE; out.samples = samples;\n"
        "  } catch (e) {\n"
        "    out.error = String((e && e.stack) || e);\n"
        "  } finally {\n"
        "    window.__result = out;\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )
    return f'<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n<body>\n{page_html}\n{harness}</body>\n</html>\n'


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    CONFIG = PathConfig()
    SETUP_ROOT: Path = CONFIG.outputs / "jsperf" / "setup"
    STEP1_BENCH: Path = SETUP_ROOT / "step1" / "benchmark"
    STEP3_BENCH: Path = SETUP_ROOT / "step3" / "benchmark"
    STEP4_TAGS: Path = SETUP_ROOT / "step4" / "tags.jsonl"
    STEP6_OUT: Path = SETUP_ROOT / "step6"
    STEP6_OUT.mkdir(parents=True, exist_ok=True)

    NODE_MEASURE_ROOT: Path = CONFIG.data / "jsPerf" / "Node" / "measure"
    PW_MEASURE_ROOT: Path = CONFIG.data / "jsPerf" / "Playwright" / "measure"

    for p in (STEP1_BENCH, STEP4_TAGS):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")

    # 冪等性のため配置先を作り直す (前回の残骸を残さない)
    for d in (NODE_MEASURE_ROOT, PW_MEASURE_ROOT):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    # --- Section 2: タグ読み込み + 振り分け再計算 ---
    tags: list[dict] = hayalab.read_jsonl(STEP4_TAGS)
    bench_tags: dict[str, list[dict]] = defaultdict(list)
    for t in tags:
        bench_tags[t["slug_id"]].append(t)
    print(f"[step6] benchmarks total: {len(bench_tags)}  tests total: {len(tags)}")

    # --- Section 3: ベンチマーク単位の整形 ---
    node_written = 0
    npm_written = 0
    pw_written = 0
    node_missing = 0
    pw_missing = 0
    dispatch_counts: Counter[str] = Counter()

    for slug_id in sorted(bench_tags):
        tests = sorted(bench_tags[slug_id], key=lambda r: r["test_idx"])

        kept = [t for t in tests if t["node_success"] or t["npm_success"] or t["playwright_success"]]
        if len(kept) < 2:
            dispatch_counts["excluded_insufficient_pair"] += 1
            continue
        if all(t["node_success"] for t in kept):
            env = "node"
        elif all(t["npm_success"] for t in kept):
            env = "npm"
        elif all(t["playwright_success"] for t in kept):
            env = "playwright"
        else:
            dispatch_counts["excluded_mixed_env"] += 1
            continue
        dispatch_counts[env] += 1

        if env == "playwright":
            dst_dir = PW_MEASURE_ROOT / slug_id
            dst_dir.mkdir(parents=True, exist_ok=True)
            page_html_path = STEP1_BENCH / slug_id / "page_html.html"
            page_html = page_html_path.read_text(encoding="utf-8") if page_html_path.exists() else ""
            for t in kept:
                program_path = STEP1_BENCH / slug_id / f"program_{t['test_idx']}.js"
                if not program_path.exists():
                    pw_missing += 1
                    continue
                harness = _build_playwright_measure(slug_id, t["test_idx"], page_html, program_path.read_text(encoding="utf-8"))
                (dst_dir / f"bench_{t['test_idx']}.measure.html").write_text(harness, encoding="utf-8")
                pw_written += 1
        else:
            dst_dir = NODE_MEASURE_ROOT / slug_id
            dst_dir.mkdir(parents=True, exist_ok=True)
            for t in kept:
                step1_path = STEP1_BENCH / slug_id / f"program_{t['test_idx']}.js"
                if not step1_path.exists():
                    node_missing += 1
                    continue
                body = step1_path.read_text(encoding="utf-8")
                require_block = ""
                if env == "npm":
                    step3_path = STEP3_BENCH / slug_id / f"program_{t['test_idx']}.js"
                    if not step3_path.exists():
                        node_missing += 1
                        continue
                    require_block = _extract_require_block(step3_path.read_text(encoding="utf-8"), body) or ""
                result_name = f"bench_{t['test_idx']}.result.json"
                harness = _build_node_measure(slug_id, t["test_idx"], body, result_name, require_block)
                (dst_dir / f"bench_{t['test_idx']}.measure.js").write_text(harness, encoding="utf-8")
                if env == "npm":
                    npm_written += 1
                else:
                    node_written += 1

    # --- Section 4: 集計 (summary.json) ---
    summary = {
        "k_warmup": K_WARMUP,
        "n_batch": N_BATCH,
        "m_measure": M_MEASURE,
        "dispatch_counts": dict(sorted(dispatch_counts.items())),
        "node_measure_written": node_written,
        "npm_measure_written": npm_written,
        "playwright_measure_written": pw_written,
        "node_program_missing": node_missing,
        "playwright_program_missing": pw_missing,
    }
    hayalab.write_json(STEP6_OUT / "summary.json", summary)

    # --- Section 5: 進捗レポート ---
    print(f"[step6] K_WARMUP={K_WARMUP} N_BATCH={N_BATCH} M_MEASURE={M_MEASURE}")
    print(f"[step6] dispatch: {dict(sorted(dispatch_counts.items()))}")
    print(f"[step6] node measure:       {node_written} (node) + {npm_written} (npm)  (missing: {node_missing})")
    print(f"[step6] playwright measure: {pw_written}  (missing: {pw_missing})")
    print(f"[step6] programs placed: {NODE_MEASURE_ROOT}  /  {PW_MEASURE_ROOT}")
    print(f"[step6] summary: {STEP6_OUT / 'summary.json'}")
