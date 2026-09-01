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

`--resume` を付けると本計測の results ファイルを読み取り専用で参照し、未完了のベンチだけを
計測する。本計測の成果物は書き換えず、再計測分は results_retry 系列へ分離して出力するため、
merge 前の原本は常に保全される。`--redo-status error` のように status を指定すると、その
status のレコードは完了済みでも未計測扱いにする。

再計測時のシャード割当は本計測の割当を引き継がず、未完了ベンチを全シャードへ均等に再配分する
(本計測で 1 シャードだけが残っても全コアで分担できる)。未完了判定はベンチ単位で行い、部分的に
計測済みのベンチは全 test を計測し直す (ペア内の全 test を同一コア・同一セッションに揃える)。

`--num-shards N --shard i` でベンチ単位にシャード分割できる (擬似並列)。同一 slug_id は
必ず同一シャードに割り当てるため、ペア (同一ベンチ内の test 群) は 1 つの実行環境で計測され、
ペア内の相対比較の妥当性が保たれる。分割時の出力は results.shard{i}.jsonl。
シャードごとに別コアへ pin して並列実行し、merge_shards.py で結合する想定。

入力:
- `data/jsPerf/Node/measure/<slug_id>/bench_<i>.measure.js` (step6 が配置)

出力: `outputs/jsperf/measure/Node/`
- `results.jsonl` (分割時は `results.shard{i}.jsonl`): per-test 計測結果
  (slug_id, test_idx, status, batch, warmup, rounds, samples_ns, elapsed_sec)
- `summary.json` (分割時は `summary.shard{i}.json`): 集計 (status 内訳、経過時間)
- `--resume` 時は上記を読むだけで、`results_retry.shard{i}.jsonl` /
  `summary_retry.shard{i}.json` に再計測分のみを書き出す (レコード schema は同一)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

import hayalab
from hayalab.config import PathConfig
from hayalab.jsperf import measure as jsperf_measure

# --- Constants ------------------------------------------------------
NODE_BIN: str = "node"
TIMEOUT_SEC: float = 180000.0  # per-test タイムアウト (重いユニットは打ち切って timeout 記録)
PROGRESS_EVERY: int = 100
STDERR_HEAD_BYTES: int = 8192  # stderr の一時ファイルから読み出す先頭バイト数
ERROR_HEAD_CHARS: int = 300  # results.jsonl の error_head に残す文字数


# --- Helpers (複数回呼び出し / per-record worker) --------------------
def _parse_test_idx(measure_js: Path) -> int:
    """`bench_<i>.measure.js` のパスから test_idx を取り出す.

    Args:
        measure_js: `bench_<i>.measure.js` のパス.

    Returns:
        test のインデックス i。
    """
    return int(measure_js.stem.split(".")[0].split("_")[1])  # "bench_<i>.measure" → i


def _run_one(measure_js: Path) -> dict:
    """1 つの measure.js を node で実行し result.json を回収する.

    Args:
        measure_js: `bench_<i>.measure.js` のパス (親ディレクトリ名が slug_id).

    Returns:
        results.jsonl 1 行分の dict (status / samples_ns 等)。
    """
    slug_id = measure_js.parent.name
    test_idx = _parse_test_idx(measure_js)
    result_path = measure_js.parent / f"bench_{test_idx}.result.json"
    # 前回の結果を消し、この実行で書かれたものだけを回収対象にする
    if result_path.exists():
        result_path.unlink()

    rec: dict = {"slug_id": slug_id, "test_idx": test_idx, "env": "node"}
    start = time.perf_counter()
    # samples は result.json 経由で受け取るため stdout は使わない。大量出力するハーネスを
    # 親プロセスのメモリに溜め込まないよう捨てる。 stderr は一時ファイルへ逃がし、
    # error_head 用に先頭だけを読み出す。
    with tempfile.TemporaryFile() as err_fp:
        try:
            proc = subprocess.run(
                [NODE_BIN, str(measure_js)],
                stdout=subprocess.DEVNULL,
                stderr=err_fp,
                timeout=TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            rec.update(status="timeout", elapsed_sec=time.perf_counter() - start, error_head="")
            return rec

        elapsed = time.perf_counter() - start
        if proc.returncode != 0 or not result_path.exists():
            err_fp.seek(0)
            err_head = err_fp.read(STDERR_HEAD_BYTES).decode("utf-8", errors="replace")
            rec.update(status="error", elapsed_sec=elapsed, error_head=err_head[:ERROR_HEAD_CHARS])
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
    # --- Section 1: 引数・パス解決 ---
    parser = argparse.ArgumentParser(description="Node 実行時間計測 (ベンチ単位シャード対応).")
    parser.add_argument("--shard", type=int, default=0, help="担当シャード番号 (0-based)")
    parser.add_argument("--num-shards", type=int, default=1, help="総シャード数 (1 = 分割なし)")
    parser.add_argument("--resume", action="store_true", help="既存 results を参照し、未計測分のみを results_retry へ出力する")
    parser.add_argument("--redo-status", default="", help="--resume 時に再計測対象へ含める status のカンマ区切り (例: error)")
    args = parser.parse_args()
    if not (0 <= args.shard < args.num_shards):
        raise SystemExit(f"invalid shard: shard={args.shard} num_shards={args.num_shards}")

    CONFIG = PathConfig()
    MEASURE_ROOT: Path = CONFIG.data / "jsPerf" / "Node" / "measure"
    OUT: Path = CONFIG.outputs / "jsperf" / "measure" / "Node"
    OUT.mkdir(parents=True, exist_ok=True)

    if not MEASURE_ROOT.exists():
        raise SystemExit(f"missing input: {MEASURE_ROOT}")

    # --- Section 2: 計測対象の列挙 ---
    all_files: list[Path] = sorted(MEASURE_ROOT.glob("*/bench_*.measure.js"))
    tests_by_slug: dict[str, list[int]] = {}
    for p in all_files:
        tests_by_slug.setdefault(p.parent.name, []).append(_parse_test_idx(p))
    suffix = f".shard{args.shard}" if args.num_shards > 1 else ""
    results_path = OUT / f"results{suffix}.jsonl"
    summary_path = OUT / f"summary{suffix}.json"

    # --- Section 3: 担当ベンチの決定 (同一 slug_id は同一シャード = 同一コア) ---
    if args.resume:
        # 本計測の成果物は参照のみ。再計測分は別系列へ出して原本を保全する
        results_path = OUT / f"results_retry{suffix}.jsonl"
        summary_path = OUT / f"summary_retry{suffix}.json"
        redo_status: set[str] = {s.strip() for s in args.redo_status.split(",") if s.strip()}
        # 全シャードが同じ done 集合を見るよう、参照元は全コンテナ共通のファイルに限る
        # (自分の出力を混ぜると再配分がシャード間でずれて取りこぼし・二重計測が起きる)
        done_keys: set[tuple[str, int]] = set()
        for path in (*sorted(OUT.glob("results.shard*.jsonl")), OUT / "results.jsonl", OUT / "result_retry.jsonl"):
            if path.exists():
                done_keys |= {(r["slug_id"], r["test_idx"]) for r in hayalab.read_jsonl(path) if r["status"] not in redo_status}
        # 残りベンチを全シャードへ均等に再配分する (本計測の割当は引き継がない)
        target_slugs = jsperf_measure.incomplete_slugs(tests_by_slug, done_keys)
        print(f"[measure-node] shard {args.shard}: resume: done {len(done_keys)} tests, incomplete {len(target_slugs)} benchmarks (redo_status={sorted(redo_status)})")
    else:
        target_slugs = sorted(tests_by_slug)

    shard_slugs = jsperf_measure.assign_shard_slugs(target_slugs, args.num_shards, args.shard)
    measure_files: list[Path] = [p for p in all_files if p.parent.name in shard_slugs]
    if args.resume and results_path.exists():
        # 同一セッション内で自分が落ちた場合の再開分だけを取り除く (シャード割当には影響しない)
        mine = {(r["slug_id"], r["test_idx"]) for r in hayalab.read_jsonl(results_path) if r["status"] not in redo_status}
        measure_files = [p for p in measure_files if (p.parent.name, _parse_test_idx(p)) not in mine]
    print(f"[measure-node] shard {args.shard}/{args.num_shards}: {len(shard_slugs)} benchmarks, {len(measure_files)} tests (timeout={TIMEOUT_SEC}s/test)")

    # --- Section 4: 直列実行 (results ファイルへ逐次追記) ---
    # --resume で既存の再計測分があるときは追記モードにし、途中まで計測済みの分を失わない
    append = args.resume and results_path.exists()
    start = time.perf_counter()
    results: list[dict] = []
    with open(results_path, "a" if append else "w", encoding="utf-8") as fp:
        for i, measure_js in enumerate(measure_files, 1):
            rec = _run_one(measure_js)
            results.append(rec)
            fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fp.flush()
            if i % PROGRESS_EVERY == 0:
                done = Counter(r["status"] for r in results)
                print(f"[measure-node] shard {args.shard}: {i}/{len(measure_files)}  {dict(done)}")
    elapsed_sec = time.perf_counter() - start

    # --- Section 5: 確定版 (重複排除 + ソート) 書き戻し ---
    # 追記モードでは過去分も含めてファイルから読み直し、同一キーは後勝ちで一意化する
    if append:
        results = list(hayalab.read_jsonl(results_path))
    by_key = {(r["slug_id"], r["test_idx"]): r for r in results}
    results = sorted(by_key.values(), key=lambda r: (r["slug_id"], r["test_idx"]))
    hayalab.write_jsonl(results_path, results)

    # --- Section 6: 集計 (summary.json) ---
    status_counts: Counter[str] = Counter(r["status"] for r in results)
    summary = {
        "env": "node",
        "shard": args.shard,
        "num_shards": args.num_shards,
        "timeout_sec": TIMEOUT_SEC,
        "elapsed_sec": elapsed_sec,
        "total_tests": len(results),
        "status_counts": {k: status_counts.get(k, 0) for k in ("success", "error", "timeout")},
    }
    hayalab.write_json(summary_path, summary)

    # --- Section 7: 進捗レポート ---
    print(f"[measure-node] shard {args.shard}/{args.num_shards} done, elapsed: {elapsed_sec:.1f}s")
    print(f"[measure-node] status_counts: {summary['status_counts']}")
    print(f"[measure-node] outputs: {results_path}")
