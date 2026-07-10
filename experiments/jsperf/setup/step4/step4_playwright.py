"""Step 4: Playwright (headless Chromium) 実行.

Node (素版/npm 注入版) で全 test 成功に到達しなかったベンチマークを対象に、
Step 1 の page_html.html (外部 <script src> + DOM 要素) と program_<i>.js (素版) を
薄い HTML ラッパで結合し、ローカル HTTP サーバ経由で Chromium にロードして実行する。

実行実体は benchmark/<slug_id>/ に自己完結させる (step1/step3 と同じ流儀):
program_<i>.js は step1 から無加工コピーし、bench_<i>.html は同ディレクトリの
program を相対パスで fetch する。

bench_<i>.html の構造 (program は inline 埋め込みしない):

    <!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
    {page_html.html の内容そのまま}
    <script>
    // fetch + new Function(src) で program を関数としてコンパイル・実行する。
    // Step 6 の計測ハーネス (unit = new Function(src) を反復呼び出し) と同一の
    // スコープ・コンパイル形式で実行可能性を検証するための形式
    (async () => { ... const unit = new Function(src); unit(); ... })();
    </script>
    </body></html>

program 実行中の例外はハーネスが window.__bench_error に格納する。
成功判定: ページロード完了 → __bench_done 到達 → settle 待機の間に
__bench_error / pageerror / console.error / 外部 script 取得失敗 がゼロであること。

error_type (原因志向の優先順位):
    LoadFailed > Timeout > ScriptLoadFailed > PageError > ConsoleError

入力:
- `outputs/jsperf/setup/step1/<slug_id>/(page_html.html, program_<i>.js, meta.json)`
- `outputs/jsperf/setup/step3/tags.jsonl` (node_success / npm_success)

出力: `outputs/jsperf/setup/step4/`
- `benchmark/<slug_id>/bench_<i>.html`: 実行用 HTML ラッパ
- `benchmark/<slug_id>/program_<i>.js`: step1 からの無加工コピー (実行された実体)
- `results.jsonl`: per-test 実行結果 (status, error_type, error_head, program_error, failed_requests, elapsed)
- `tags.jsonl`: 全 program のタグ (node_success / npm_success / playwright_success を独立保持)
- `summary.json`: 集計 (error_type 内訳、benchmark 単位、失敗 script URL ホスト別上位)
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import threading
import time
from collections import Counter, defaultdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

import hayalab
from hayalab.config import PathConfig

# --- Constants ------------------------------------------------------
DEFAULT_MAX_WORKERS: int = 25
DEFAULT_PAGE_TIMEOUT_MS: int = 30_000
DEFAULT_SETTLE_MS: int = 500
DEFAULT_PORT: int = 8437
ERROR_TYPE_KEYS: tuple[str, ...] = (
    "LoadFailed",
    "Timeout",
    "ScriptLoadFailed",
    "PageError",
    "ConsoleError",
)


# --- Helpers (複数回呼び出し / per-record worker) --------------------
class _CoepHandler(SimpleHTTPRequestHandler):
    """docroot 配信 + COOP/COEP ヘッダ付与を行うローカル HTTP ハンドラ."""

    coep_mode: str = "credentialless"

    def end_headers(self) -> None:  # noqa: D102
        if self.coep_mode != "none":
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", self.coep_mode)
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002, D102
        pass


def _build_bench_html(page_html: str, program_src: str) -> str:
    """1 test 分の bench HTML を生成する.

    program は fetch + new Function(src) で関数としてコンパイルして 1 回実行する
    (Step 6 の計測ハーネスと同一のスコープ・コンパイル形式)。 実行中の例外は
    window.__bench_error に格納し、完了マーカーとして window.__bench_done を立てる。

    Args:
        page_html: step1 の page_html.html の内容 (無ければ空文字).
        program_src: program_<i>.js の fetch パス (bench HTML と同ディレクトリの相対パス).

    Returns:
        bench_<i>.html の内容.
    """
    harness = (
        "<script>\n"
        "(async () => {\n"
        "  try {\n"
        f'    const res = await fetch("{program_src}");\n'
        '    if (!res.ok) throw new Error("program fetch failed: HTTP " + res.status);\n'
        "    const src = await res.text();\n"
        "    const unit = new Function(src);\n"
        "    unit();\n"
        "  } catch (e) {\n"
        "    window.__bench_error = String((e && e.stack) || e);\n"
        "  } finally {\n"
        "    window.__bench_done = true;\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )
    return f'<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n<body>\n{page_html}\n{harness}</body>\n</html>\n'


async def _run_bench_page(context, url: str, timeout_ms: int, settle_ms: int) -> dict:
    """1 つの bench HTML を新規ページで実行し、結果を分類する per-record worker.

    Args:
        context: Playwright BrowserContext (worker 内で共有し HTTP キャッシュを効かせる).
        url: bench HTML の URL.
        timeout_ms: goto + マーカー待ちのタイムアウト.
        settle_ms: マーカー到達後にエラーを回収する待機時間.

    Returns:
        status / error_type / error_head / program_error / failed_requests /
        n_console_errors / elapsed を持つ dict.
    """
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[dict] = []
    program_error: str | None = None

    page = await context.new_page()
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    # リソース 404 由来の console.error は除外する (script の取得失敗は
    # failed_requests 側で kind 付きで捕捉するため、ここで数えると img 等の欠落で
    # テスト自体は成功しているページを fail 扱いしてしまう)
    page.on(
        "console",
        lambda m: console_errors.append(m.text) if m.type == "error" and not m.text.startswith("Failed to load resource") else None,
    )
    page.on(
        "requestfailed",
        lambda req: failed_requests.append({"url": req.url, "reason": (req.failure or ""), "kind": req.resource_type}),
    )
    page.on(
        "response",
        lambda res: failed_requests.append({"url": res.url, "reason": f"HTTP {res.status}", "kind": res.request.resource_type}) if res.status >= 400 else None,
    )

    start = time.perf_counter()
    status = "success"
    error_type: str | None = None
    error_head = ""
    try:
        # 同期 <script src> はパーサブロッキングであり domcontentloaded 時点で
        # 実行済み。load (全サブリソース完了) を待つと応答しない img 等でハングする
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_function("() => window.__bench_done === true", timeout=timeout_ms)
        await page.wait_for_timeout(settle_ms)
        program_error = await page.evaluate("window.__bench_error || null")
    except Exception as exc:  # goto 失敗 / マーカー未達
        msg = str(exc)
        if "Timeout" in type(exc).__name__ or "timeout" in msg.lower():
            status, error_type, error_head = "timeout", "Timeout", msg[:300]
        else:
            status, error_type, error_head = "error", "LoadFailed", msg[:300]
    finally:
        elapsed = time.perf_counter() - start
        await page.close()

    script_failures = [f for f in failed_requests if f["kind"] == "script"]
    if status == "success":
        if script_failures:
            status, error_type = "error", "ScriptLoadFailed"
            error_head = "; ".join(f"{f['url']} ({f['reason']})" for f in script_failures)[:500]
        elif program_error:
            status, error_type, error_head = "error", "PageError", program_error[:500]
        elif page_errors:
            status, error_type, error_head = "error", "PageError", page_errors[0][:500]
        elif console_errors:
            status, error_type, error_head = "error", "ConsoleError", console_errors[0][:500]

    return {
        "status": status,
        "error_type": error_type,
        "error_head": error_head,
        "program_error": bool(program_error),
        "failed_requests": script_failures,
        "n_console_errors": len(console_errors),
        "elapsed": elapsed,
    }


async def _worker(browser, queue: asyncio.Queue, results: list[dict], base_url: str, timeout_ms: int, settle_ms: int) -> None:
    """Queue から job を取り出して実行し続ける worker (1 worker = 1 BrowserContext)."""
    context = await browser.new_context()
    try:
        while True:
            job = await queue.get()
            if job is None:
                queue.task_done()
                break
            slug_id, slug, test_idx, html_rel = job
            res = await _run_bench_page(context, f"{base_url}/{html_rel}", timeout_ms, settle_ms)
            results.append(
                {
                    "slug_id": slug_id,
                    "slug": slug,
                    "test_idx": test_idx,
                    "path": html_rel,
                    **res,
                }
            )
            done = len(results)
            if done % 50 == 0:
                print(f"[step4] progress: {done} pages done")
            queue.task_done()
    finally:
        await context.close()


async def _run_all(jobs: list[tuple], base_url: str, max_workers: int, timeout_ms: int, settle_ms: int) -> list[dict]:
    """全 job を max_workers 並列で実行する (呼び出し 2 回: 本実行 + リトライ)."""
    results: list[dict] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        queue: asyncio.Queue = asyncio.Queue()
        for j in jobs:
            queue.put_nowait(j)
        for _ in range(max_workers):
            queue.put_nowait(None)
        workers = [asyncio.create_task(_worker(browser, queue, results, base_url, timeout_ms, settle_ms)) for _ in range(max_workers)]
        await asyncio.gather(*workers)
        await browser.close()
    return results


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数パース ---
    parser = argparse.ArgumentParser(description="Step4: Playwright execution for non-Node benchmarks.")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_PAGE_TIMEOUT_MS, help="per-page timeout (ms)")
    parser.add_argument("--settle", type=int, default=DEFAULT_SETTLE_MS, help="post-done settle wait (ms)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--coep",
        choices=["credentialless", "require-corp", "none"],
        default="credentialless",
        help="COEP header mode for the local HTTP server",
    )
    parser.add_argument("--limit", type=int, default=0, help="limit target benchmarks (0 = all; smoke 用)")
    args = parser.parse_args()

    # --- Section 2: パス解決 ---
    CONFIG = PathConfig()
    SETUP_ROOT: Path = CONFIG.outputs / "jsperf" / "setup"
    STEP1_DIR: Path = SETUP_ROOT / "step1"
    STEP3_TAGS: Path = SETUP_ROOT / "step3" / "tags.jsonl"
    STEP4_OUT: Path = SETUP_ROOT / "step4"
    STEP4_BENCH: Path = STEP4_OUT / "benchmark"
    STEP4_OUT.mkdir(parents=True, exist_ok=True)
    STEP4_BENCH.mkdir(parents=True, exist_ok=True)

    for p in (STEP1_DIR, STEP3_TAGS):
        if not p.exists():
            raise SystemExit(f"missing input: {p}")

    # --- Section 3: 対象ベンチマーク選定 ---
    step3_tags: list[dict] = hayalab.read_jsonl(STEP3_TAGS)
    bench_tags: dict[str, list[dict]] = defaultdict(list)
    for t in step3_tags:
        bench_tags[t["slug_id"]].append(t)

    target_slug_ids: list[str] = sorted(slug_id for slug_id, recs in bench_tags.items() if not all(r.get("node_success", False) or r.get("npm_success", False) for r in recs))
    print(f"[step4] benchmarks total:          {len(bench_tags)}")
    print(f"[step4] target (not node-capable): {len(target_slug_ids)}")

    skipped_no_step1: int = 0
    available_slug_ids: list[str] = []
    for slug_id in target_slug_ids:
        if (STEP1_DIR / slug_id).is_dir():
            available_slug_ids.append(slug_id)
        else:
            skipped_no_step1 += 1
    print(f"[step4] skipped (no step1 dir):    {skipped_no_step1}")
    if args.limit > 0:
        available_slug_ids = available_slug_ids[: args.limit]
    print(f"[step4] to run:                    {len(available_slug_ids)} benchmarks")

    # --- Section 4: 実行実体の集約 (program コピー + bench HTML 生成) ---
    jobs: list[tuple[str, str, int, str]] = []
    skipped_no_program: int = 0
    for slug_id in available_slug_ids:
        page_html_path = STEP1_DIR / slug_id / "page_html.html"
        page_html: str = page_html_path.read_text(encoding="utf-8") if page_html_path.exists() else ""
        for rec in sorted(bench_tags[slug_id], key=lambda r: r["test_idx"]):
            test_idx: int = rec["test_idx"]
            src_program = STEP1_DIR / slug_id / f"program_{test_idx}.js"
            if not src_program.exists():
                skipped_no_program += 1
                continue
            dst_dir = STEP4_BENCH / slug_id
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_program, dst_dir / f"program_{test_idx}.js")
            html = _build_bench_html(page_html, f"program_{test_idx}.js")
            (dst_dir / f"bench_{test_idx}.html").write_text(html, encoding="utf-8")
            jobs.append((slug_id, rec["slug"], test_idx, f"benchmark/{slug_id}/bench_{test_idx}.html"))

    print(f"[step4] skipped (no program js):   {skipped_no_program}")
    print(f"[step4] pages to run:              {len(jobs)}")

    # --- Section 5: ローカル HTTP サーバ起動 (docroot = step4 出力ディレクトリ) ---
    _CoepHandler.coep_mode = args.coep
    handler = partial(_CoepHandler, directory=str(STEP4_OUT))
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{args.port}"
    print(f"[step4] http server: {base_url}  (docroot={STEP4_OUT}, coep={args.coep})")

    # --- Section 6: Playwright 実行 (本実行 + fail のみ 1 回リトライ) ---
    start = time.perf_counter()
    results: list[dict] = asyncio.run(_run_all(jobs, base_url, args.max_workers, args.timeout, args.settle))

    failed_jobs = [(r["slug_id"], r["slug"], r["test_idx"], r["path"]) for r in results if r["status"] != "success"]
    if failed_jobs:
        print(f"[step4] retrying {len(failed_jobs)} failed pages once...")
        retry_results = asyncio.run(_run_all(failed_jobs, base_url, args.max_workers, args.timeout, args.settle))
        retry_map = {(r["slug_id"], r["test_idx"]): r for r in retry_results}
        merged: list[dict] = []
        for r in results:
            key = (r["slug_id"], r["test_idx"])
            if r["status"] != "success" and key in retry_map and retry_map[key]["status"] == "success":
                merged.append(retry_map[key])
            else:
                merged.append(r)
        results = merged

    elapsed_sec = time.perf_counter() - start
    httpd.shutdown()
    results.sort(key=lambda x: (x["slug_id"], x["test_idx"]))

    # --- Section 7: results.jsonl / tags.jsonl 書き出し ---
    hayalab.write_jsonl(STEP4_OUT / "results.jsonl", results)

    pw_success: set[tuple[str, int]] = {(r["slug_id"], r["test_idx"]) for r in results if r["status"] == "success"}
    tags_out: list[dict] = []
    for rec in step3_tags:
        key = (rec["slug_id"], rec["test_idx"])
        tags_out.append(
            {
                "slug_id": rec["slug_id"],
                "slug": rec["slug"],
                "test_idx": rec["test_idx"],
                "node_success": bool(rec.get("node_success", False)),
                "npm_success": bool(rec.get("npm_success", False)),
                "playwright_success": key in pw_success,
            }
        )
    tags_out.sort(key=lambda x: (x["slug_id"], x["test_idx"]))
    hayalab.write_jsonl(STEP4_OUT / "tags.jsonl", tags_out)

    # --- Section 8: 集計 (summary.json) ---
    status_counts_c: Counter[str] = Counter(r["status"] for r in results)
    error_type_counts_c: Counter[str] = Counter(r["error_type"] for r in results if r["error_type"])
    error_type_counts = {k: error_type_counts_c.get(k, 0) for k in ERROR_TYPE_KEYS}

    ran_bench: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        ran_bench[r["slug_id"]].append(r["status"] == "success")
    bench_all = sum(1 for f in ran_bench.values() if f and all(f))
    bench_partial = sum(1 for f in ran_bench.values() if f and any(f) and not all(f))
    bench_none = sum(1 for f in ran_bench.values() if f and not any(f))

    failed_hosts: Counter[str] = Counter()
    failed_urls: Counter[str] = Counter()
    for r in results:
        for f in r.get("failed_requests", []):
            host = urlparse(f["url"]).netloc
            failed_hosts[host] += 1
            failed_urls[f["url"]] += 1

    summary = {
        "elapsed_sec": elapsed_sec,
        "max_workers": args.max_workers,
        "coep_mode": args.coep,
        "page_timeout_ms": args.timeout,
        "benchmarks_total": len(bench_tags),
        "target_benchmarks": len(target_slug_ids),
        "skipped_no_step1": skipped_no_step1,
        "ran_benchmarks": len(ran_bench),
        "ran_pages": len(results),
        "status_counts": {
            "success": status_counts_c.get("success", 0),
            "error": status_counts_c.get("error", 0),
            "timeout": status_counts_c.get("timeout", 0),
        },
        "error_type_counts": error_type_counts,
        "playwright_success_total": len(pw_success),
        "benchmark_summary": {
            "benchmarks_all_success": bench_all,
            "benchmarks_partial_success": bench_partial,
            "benchmarks_all_failed": bench_none,
        },
        "failed_script_hosts_top": dict(failed_hosts.most_common(40)),
        "failed_script_urls_top": dict(failed_urls.most_common(40)),
    }
    hayalab.write_json(STEP4_OUT / "summary.json", summary)

    # --- Section 9: 進捗レポート ---
    print(f"[step4] elapsed: {elapsed_sec:.1f}s")
    print(f"[step4] status_counts: {summary['status_counts']}")
    print(f"[step4] error_type_counts: {error_type_counts}")
    print(f"[step4] benchmark_summary: {summary['benchmark_summary']}")
    print(f"[step4] top failed script hosts: {dict(failed_hosts.most_common(10))}")
    print(f"[step4] outputs: {STEP4_OUT}")
