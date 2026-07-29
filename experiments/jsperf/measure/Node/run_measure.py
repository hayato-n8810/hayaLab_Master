"""Node 環境の実行時間計測: measure ハーネスを node 実行し samples を集約する.

npm 版ハーネスの require 依存はコンテナ構築時に /opt/npm へインストール済みで、NODE_PATH が
その node_modules を指す (Dockerfile / docker-compose 参照)。

step6 が配置した `data/jsPerf/Node/measure/<slug_id>/bench_<i>.measure.js` を 1 つずつ
`node` で直列実行する (計測はコア競合を避けるため並列化しない)。各ハーネスは実行すると
同ディレクトリの `bench_<i>.result.json` へ samples (ns) を fs で書き出すので、それを
回収して `outputs/jsperf/measure/Node/results.jsonl` に集約する。

実行結果の分類:
- success: node が正常終了し result.json が書かれた (samples 回収)
- error: node が異常終了 / result.json が書かれなかった (program の実行時例外等)
- timeout: TIMEOUT_SEC 内に終わらなかった (重いユニット・無限ループ。受容して記録)

results.jsonl は完了順に逐次追記し、終了時に (slug_id, test_idx) ソートの確定版を書き戻す
(長時間実行の途中でプロセスが落ちても完了分は残す)。

入力:
- `data/jsPerf/Node/measure/<slug_id>/bench_<i>.measure.js` (step6 が配置)

出力: `outputs/jsperf/measure/Node/`
- `results.jsonl`: per-test 計測結果 (slug_id, test_idx, status, batch, warmup, rounds, samples_ns, elapsed_sec)
- `summary.json`: 集計 (status 内訳、経過時間)
"""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from pathlib import Path

import hayalab
from hayalab.config import PathConfig

# --- Constants ------------------------------------------------------
NODE_BIN: str = "node"
TIMEOUT_SEC: float = 1000.0  # per-test タイムアウト (重いユニットは打ち切って timeout 記録)
PROGRESS_EVERY: int = 100


# --- Helpers (per-record worker) -----------------------------------
def _run_one(measure_js: Path) -> dict:
    """1 つの measure.js を node で実行し result.json を回収する.

    Args:
        measure_js: `bench_<i>.measure.js` のパス (親ディレクトリ名が slug_id).

    Returns:
        results.jsonl 1 行分の dict (status / samples_ns 等)。
    """
    slug_id = measure_js.parent.name
    test_idx = int(measure_js.stem.split(".")[0].split("_")[1])  # "bench_<i>.measure" → i
    result_path = measure_js.parent / f"bench_{test_idx}.result.json"
    # 前回の結果を消し、この実行で書かれたものだけを回収対象にする
    if result_path.exists():
        result_path.unlink()

    rec: dict = {"slug_id": slug_id, "test_idx": test_idx, "env": "node"}
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            [NODE_BIN, str(measure_js)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        rec.update(status="timeout", elapsed_sec=time.perf_counter() - start, error_head="")
        return rec

    elapsed = time.perf_counter() - start
    if proc.returncode != 0 or not result_path.exists():
        rec.update(status="error", elapsed_sec=elapsed, error_head=(proc.stderr or "")[:300])
        return rec

    data = json.loads(result_path.read_text(encoding="utf-8"))
    rec.update(
        status="success",
        elapsed_sec=elapsed,
        batch=data["batch"],
        warmup=data["warmup"],
        rounds=data["rounds"],
        samples_ns=data["samples"],
    )
    return rec


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    CONFIG = PathConfig()
    MEASURE_ROOT: Path = CONFIG.data / "jsPerf" / "Node" / "measure"
    OUT: Path = CONFIG.outputs / "jsperf" / "measure" / "Node"
    OUT.mkdir(parents=True, exist_ok=True)

    if not MEASURE_ROOT.exists():
        raise SystemExit(f"missing input: {MEASURE_ROOT}")

    # --- Section 2: 計測対象の列挙 (決定的順序) ---
    measure_files: list[Path] = sorted(MEASURE_ROOT.glob("*/bench_*.measure.js"))
    print(f"[measure-node] targets: {len(measure_files)}  (timeout={TIMEOUT_SEC}s/test)")

    # --- Section 3: 直列実行 (results.jsonl へ逐次追記) ---
    results_path = OUT / "results.jsonl"
    start = time.perf_counter()
    results: list[dict] = []
    with open(results_path, "w", encoding="utf-8") as fp:
        for i, measure_js in enumerate(measure_files, 1):
            rec = _run_one(measure_js)
            results.append(rec)
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()
            if i % PROGRESS_EVERY == 0:
                done = Counter(r["status"] for r in results)
                print(f"[measure-node] {i}/{len(measure_files)}  {dict(done)}")
    elapsed_sec = time.perf_counter() - start

    # --- Section 4: 確定版 (ソート) 書き戻し ---
    results.sort(key=lambda r: (r["slug_id"], r["test_idx"]))
    hayalab.write_jsonl(results_path, results)

    # --- Section 5: 集計 (summary.json) ---
    status_counts: Counter[str] = Counter(r["status"] for r in results)
    summary = {
        "env": "node",
        "timeout_sec": TIMEOUT_SEC,
        "elapsed_sec": elapsed_sec,
        "total_tests": len(results),
        "status_counts": {k: status_counts.get(k, 0) for k in ("success", "error", "timeout")},
    }
    hayalab.write_json(OUT / "summary.json", summary)

    # --- Section 6: 進捗レポート ---
    print(f"[measure-node] elapsed: {elapsed_sec:.1f}s")
    print(f"[measure-node] status_counts: {summary['status_counts']}")
    print(f"[measure-node] outputs: {OUT}")
