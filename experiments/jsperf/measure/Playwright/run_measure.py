"""Playwright 環境の実行時間計測: measure ハーネスを Chromium で実行し samples を集約する.

step6 が配置した `data/jsPerf/Playwright/measure/<slug_id>/bench_<i>.measure.html` を 1 つずつ
ローカル HTTP サーバ経由で headless Chromium にロードして直列実行する (計測はコア競合を
避けるため並列化しない)。各ハーネスは performance.now() で計測した samples (ms) を
window.__result に格納するので、page.evaluate で回収して
`outputs/jsperf/measure/Playwright/results.jsonl` に集約する (ブラウザはファイルに直接
書けないため、Node 環境の fs 直書きと異なり回収側で書き出す)。

HTTP サーバは COOP: same-origin / COEP: credentialless を付与し、crossOriginIsolated を
成立させて performance.now() の高精度モードを使えるようにする (step4 と同じ)。 BrowserContext
は HTML ごとに作り直し、同一オリジンの localStorage / IndexedDB / cookie が前のテストから
漏れないようにする。 driver/browser が死亡した場合は browser を再起動して続行する。

実行結果の分類:
- success: window.__result に samples が入った (回収成功)
- error: window.__result.error が入った (program の実行時例外) / driver 死亡等
- timeout: PAGE_TIMEOUT_MS 内にロード完了・__result 到達しなかった (重いユニット・無限ループ)

results.jsonl は完了順に逐次追記し、終了時に (slug_id, test_idx) ソートの確定版を書き戻す。

入力:
- `data/jsPerf/Playwright/measure/<slug_id>/bench_<i>.measure.html` (step6 が配置)

出力: `outputs/jsperf/measure/Playwright/`
- `results.jsonl`: per-test 計測結果 (slug_id, test_idx, status, batch, warmup, rounds, samples_ms, elapsed_sec)
- `summary.json`: 集計 (status 内訳、経過時間)
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright

import hayalab
from hayalab.config import PathConfig

# --- Constants ------------------------------------------------------
PORT: int = 8500
COEP_MODE: str = "credentialless"
PAGE_TIMEOUT_MS: int = 1_000_000  # per-test タイムアウト (重いユニットは打ち切って timeout 記録)
PROGRESS_EVERY: int = 100


# --- Helpers (複数回呼び出し / per-record worker) --------------------
class _CoepHandler(SimpleHTTPRequestHandler):
    """docroot 配信 + COOP/COEP ヘッダ付与を行うローカル HTTP ハンドラ."""

    def end_headers(self) -> None:  # noqa: D102
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", COEP_MODE)
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A002, D102
        pass


async def _measure_one(browser, url: str, slug_id: str, test_idx: int, timeout_ms: int) -> dict:
    """1 つの measure.html をロードし window.__result を回収する per-record worker.

    Args:
        browser: Playwright Browser.
        url: measure.html の URL.
        slug_id: ベンチマークの slug_id.
        test_idx: test のインデックス.
        timeout_ms: goto / __result 待ちのタイムアウト.

    Returns:
        results.jsonl 1 行分の dict (status / samples_ms 等)。
    """
    rec: dict = {"slug_id": slug_id, "test_idx": test_idx, "env": "playwright"}
    context = await browser.new_context()
    start = time.perf_counter()
    try:
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        await page.wait_for_function("() => window.__result !== undefined", timeout=timeout_ms)
        out = await page.evaluate("window.__result")
        elapsed = time.perf_counter() - start
        if out.get("error"):
            rec.update(status="error", elapsed_sec=elapsed, error_head=str(out["error"])[:300])
        else:
            rec.update(
                status="success",
                elapsed_sec=elapsed,
                batch=out["batch"],
                warmup=out["warmup"],
                rounds=out["rounds"],
                samples_ms=out["samples"],
            )
    except Exception as exc:
        elapsed = time.perf_counter() - start
        msg = str(exc)
        status = "timeout" if ("Timeout" in type(exc).__name__ or "timeout" in msg.lower()) else "error"
        rec.update(status=status, elapsed_sec=elapsed, error_head=msg[:300])
    finally:
        # driver 死亡後は close 不能のため失敗は無視する
        try:
            await context.close()
        except Exception:
            pass
    return rec


async def _measure_all(jobs: list[tuple[str, int, str]], base_url: str, timeout_ms: int, results_fp) -> list[dict]:
    """全 measure.html を直列実行し results_fp へ逐次追記する (driver 死亡時は browser 再起動)."""
    results: list[dict] = []
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    try:
        for i, (slug_id, test_idx, rel) in enumerate(jobs, 1):
            rec = await _measure_one(browser, f"{base_url}/{rel}", slug_id, test_idx, timeout_ms)
            # driver/browser 死亡を検知したら再起動して続行する
            if not browser.is_connected():
                try:
                    await pw.stop()
                except Exception:
                    pass
                pw = await async_playwright().start()
                browser = await pw.chromium.launch(headless=True)
                print(f"[measure-pw] driver crashed; relaunched ({slug_id}/bench_{test_idx})")
            results.append(rec)
            results_fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            results_fp.flush()
            if i % PROGRESS_EVERY == 0:
                done = Counter(r["status"] for r in results)
                print(f"[measure-pw] {i}/{len(jobs)}  {dict(done)}")
    finally:
        try:
            await browser.close()
        except Exception:
            pass
        try:
            await pw.stop()
        except Exception:
            pass
    return results


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    CONFIG = PathConfig()
    MEASURE_ROOT: Path = CONFIG.data / "jsPerf" / "Playwright" / "measure"
    OUT: Path = CONFIG.outputs / "jsperf" / "measure" / "Playwright"
    OUT.mkdir(parents=True, exist_ok=True)

    if not MEASURE_ROOT.exists():
        raise SystemExit(f"missing input: {MEASURE_ROOT}")

    # --- Section 2: 計測対象の列挙 (決定的順序) ---
    jobs: list[tuple[str, int, str]] = []
    for p in sorted(MEASURE_ROOT.glob("*/bench_*.measure.html")):
        slug_id = p.parent.name
        test_idx = int(p.stem.split(".")[0].split("_")[1])  # "bench_<i>.measure" → i
        jobs.append((slug_id, test_idx, p.relative_to(MEASURE_ROOT).as_posix()))
    print(f"[measure-pw] targets: {len(jobs)}  (timeout={PAGE_TIMEOUT_MS}ms/test)")

    # --- Section 3: ローカル HTTP サーバ起動 (docroot = measure ルート) ---
    handler = partial(_CoepHandler, directory=str(MEASURE_ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{PORT}"
    print(f"[measure-pw] http server: {base_url}  (docroot={MEASURE_ROOT}, coep={COEP_MODE})")

    # --- Section 4: 直列実行 (results.jsonl へ逐次追記) ---
    results_path = OUT / "results.jsonl"
    start = time.perf_counter()
    with open(results_path, "w", encoding="utf-8") as fp:
        results: list[dict] = asyncio.run(_measure_all(jobs, base_url, PAGE_TIMEOUT_MS, fp))
    elapsed_sec = time.perf_counter() - start
    httpd.shutdown()

    # --- Section 5: 確定版 (ソート) 書き戻し ---
    results.sort(key=lambda r: (r["slug_id"], r["test_idx"]))
    hayalab.write_jsonl(results_path, results)

    # --- Section 6: 集計 (summary.json) ---
    status_counts: Counter[str] = Counter(r["status"] for r in results)
    summary = {
        "env": "playwright",
        "coep_mode": COEP_MODE,
        "page_timeout_ms": PAGE_TIMEOUT_MS,
        "elapsed_sec": elapsed_sec,
        "total_tests": len(results),
        "status_counts": {k: status_counts.get(k, 0) for k in ("success", "error", "timeout")},
    }
    hayalab.write_json(OUT / "summary.json", summary)

    # --- Section 7: 進捗レポート ---
    print(f"[measure-pw] elapsed: {elapsed_sec:.1f}s")
    print(f"[measure-pw] status_counts: {summary['status_counts']}")
    print(f"[measure-pw] outputs: {OUT}")
