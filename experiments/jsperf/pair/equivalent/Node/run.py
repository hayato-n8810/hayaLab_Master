"""Step 1: 標準出力の比較による不等価ペアの除外.

`outputs/jsperf/pair/time/Node/pair_programs.json` の各ペアについて、fast / slow を
決定化して関数ラップし、同一プロセスの同一パスで 1 回ずつ実行する。 stdout / stderr の
ハッシュが一致しないペアを除外する。

ペアを単位として並列化するため、1 ペアの fast / slow は必ず同一ワーカープロセスで
連続実行され、スタックトレースに現れる絶対パスが両者で一致する。

入力:
- `outputs/jsperf/pair/time/Node/pair_programs.json`

出力: `outputs/jsperf/pair/equivalent/Node/`
- `equivalent_pair.json`: Step1 通過ペア (入力と同じ形式)
- `not_equivalent_pair.json`: Step1 非通過ペアと理由 (決定化失敗を含む)
- `summary.json`: 通過 / 非通過の件数と理由内訳
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from tqdm import tqdm

import hayalab
from hayalab.config import PathConfig
from hayalab.jsperf.equivalent import equivalent_output, replace_non_deterministic

# --- Constants (ファイル先頭で調整するハイパーパラメータ) ----------
CHUNK_SIZE: int = 4


# --- per-record worker ---------------------------------------------
def _judge_pair(pair: dict) -> dict:
    """1ペアの等価性検証を行う

    Args:
        pair (dict): `pair_programs.json` の 1 要素

    Returns:
        dict: `{"pair": pair, "equivalent": bool, "step": int | None, "reason": dict | None}`
            - `step`: None=等価, 0=決定化失敗, 1=標準出力不一致, # 2=変数格納値不一致, 3=式の値不一致
            - `reason`: `step` に応じた詳細情報。`step` が None の場合は None
    """
    # 非決定的な処理を置換
    fast_code, fast_status = replace_non_deterministic(pair["fast"]["code"])
    slow_code, slow_status = replace_non_deterministic(pair["slow"]["code"])

    if fast_status != "ok" or slow_status != "ok":
        step0 = {
            "detail": {"fast_status": fast_status, "slow_status": slow_status},
            "fast": {"program": pair["fast"]["code"], "determinize_status": fast_status, "stdout_head": None, "stderr_head": None},
            "slow": {"program": pair["slow"]["code"], "determinize_status": slow_status, "stdout_head": None, "stderr_head": None},
        }
        return {"pair": pair, "equivalent": False, "step": 0, "reason": step0}

    # 標準出力を比較
    is_equivalent, reason, obs_fast, obs_slow = equivalent_output(fast_code, slow_code)
    step1 = {
        "detail": reason,
        "fast": {"program": pair["fast"]["code"], "determinize_status": fast_status, "stdout_head": obs_fast["stdout_head"], "stderr_head": obs_fast["stderr_head"]},
        "slow": {"program": pair["slow"]["code"], "determinize_status": slow_status, "stdout_head": obs_slow["stdout_head"], "stderr_head": obs_slow["stderr_head"]},
    }
    if not is_equivalent:
        return {"pair": pair, "equivalent": is_equivalent, "step": 1, "reason": step1}

    # # TODO: 変数の最終格納値を比較
    # is_equivalent, reason, obs_fast, obs_slow = equivalent_value(fast_code, slow_code)
    # step2 = {
    #     "detail": reason,
    #     "fast": {"program": pair["fast"]["code"], "determinize_status": fast_status},
    #     "slow": {"program": pair["slow"]["code"], "determinize_status": slow_status},
    # }
    # if not is_equivalent:
    #     return {"pair": pair, "equivalent": is_equivalent, "step": 2, "reason": step2}

    # # TODO: 式の値を比較
    # is_equivalent, reason, obs_fast, obs_slow = equivalent_formula(fast_code, slow_code)
    # step3 = {
    #     "detail": reason,
    #     "fast": {"program": pair["fast"]["code"], "determinize_status": fast_status},
    #     "slow": {"program": pair["slow"]["code"], "determinize_status": slow_status},
    # }
    # if not is_equivalent:
    #     return {"pair": pair, "equivalent": is_equivalent, "step": 3, "reason": step3}

    return {"pair": pair, "equivalent": is_equivalent, "step": None, "reason": None}


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- 引数・パス解決 ---
    parser = argparse.ArgumentParser(description="標準出力の比較により不等価ペアを除外する.")
    parser.add_argument("--limit", type=int, default=0, help="先頭 N ペアだけ処理する (0 なら全件)")
    parser.add_argument("--workers", type=int, default=4, help="ペア単位の並列ワーカー数")
    args = parser.parse_args()

    CONFIG = PathConfig()
    INPUT_JSON = CONFIG.outputs / "jsperf" / "pair" / "time" / "Node" / "pair_programs.json"
    OUTPUT_DIR = CONFIG.outputs / "jsperf" / "pair" / "equivalent" / "Node"

    if not INPUT_JSON.exists():
        raise SystemExit(f"input not found: {INPUT_JSON}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- pair_programs.json の読み込み ---
    pairs: list[dict] = hayalab.read_json(INPUT_JSON)
    if args.limit > 0:
        pairs = pairs[: args.limit]
    print(f"[equiv-node] pairs: {len(pairs)}  workers: {args.workers}")

    # --- ペア単位の並列処理 (決定化 → 検証) ---
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for result in tqdm(executor.map(_judge_pair, pairs, chunksize=CHUNK_SIZE), total=len(pairs)):
            results.append(result)

    # --- 結果の書き出し ---
    equivalent_pairs: list[dict] = []
    not_equivalent_pairs: list[dict] = []
    for result in results:
        pair = result["pair"]
        if result["equivalent"]:
            equivalent_pairs.append(pair)
            continue
        not_equivalent_pairs.append(
            {
                "slug_id": pair["slug_id"],
                "fast_test_idx": pair["fast"]["test_id"],
                "slow_test_idx": pair["slow"]["test_id"],
                "mean_ratio": pair["mean_ratio"],
                "step": result["step"],
                "reason": result["reason"],
            }
        )

    hayalab.write_json(OUTPUT_DIR / "equivalent_pair.json", equivalent_pairs)
    hayalab.write_json(OUTPUT_DIR / "not_equivalent_pair.json", not_equivalent_pairs)

    # --- summary の書き出し ---
    reason_counts: Counter[str] = Counter(f"step{r['step']}:{r['reason']['detail']}" for r in not_equivalent_pairs)
    summary = {
        "total_pairs": len(pairs),
        "equivalent_pairs": len(equivalent_pairs),
        "not_equivalent_pairs": len(not_equivalent_pairs),
        "reason_breakdown": dict(sorted(reason_counts.items())),
    }
    hayalab.write_json(OUTPUT_DIR / "summary.json", summary)

    print(f"[equiv-node] equivalent: {summary['equivalent_pairs']} / not_equivalent: {summary['not_equivalent_pairs']}")
    print(f"[equiv-node] reason_breakdown: {summary['reason_breakdown']}")
    print(f"[equiv-node] outputs written to: {OUTPUT_DIR}")
