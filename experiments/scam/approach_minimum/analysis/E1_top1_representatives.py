"""E1 補足: 全 16 cell × 7 既知パターン × top1 クラスの代表値テーブル.

各 (τ ∈ {0.7, 0.9}, level ∈ {0, 1}, depth ∈ {Diff, Brother, ExParent, Parent})
= 16 cell について、 既知 7 パターン (1, 2, 3, 6, 7, 8, 9) の top1 クラス (= 正解事例が
最も多く集まった単一クラス) を求め、 以下を併記する:

- top1 クラス ID
- 交差数 / クラスサイズ
- mode_medoid 代表値 (strategy, value, support)
- recall / precision / F1 (top1 クラスに対して計算)

出力:
    outputs/scam/approach_minimum/analysis/E1_top1_representatives.csv (16 cell × 7 pattern = 112 行)
    outputs/scam/approach_minimum/analysis/E1_top1_representatives.json
    outputs/scam/approach_minimum/analysis/E1_top1_precision_nonzero_precision.json  (precision > 0, precision 降順)
    outputs/scam/approach_minimum/analysis/E1_top1_precision_nonzero_f1.json         (precision > 0, F1 降順)
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    DEPTHS,
    KNOWN_PATTERNS,
    LEVELS,
    TAUS,
    build_member_to_class,
    ensure_out_dir,
    load_classes,
    load_representative,
    load_rq1_ground_truth,
)

PATTERN_NAME: dict[int, str] = {
    1: "自プロパティ列挙 (for-in + hasOwnProperty)",
    2: "1 文字部分文字列 (substr(i,1))",
    3: "文字列への型変換 (String(x))",
    6: "文字列置換 (split.join)",
    7: "型判定 (toString.call)",
    8: "偶奇判定 (x % 2 === 0)",
    9: "配列の反復処理 (高階関数)",
}


def get_top1_for_pattern(tau: float, level: int, depth: str, pattern_id: int, classes: dict, mb_to_class: dict, gp: set[int]) -> dict:
    """指定 (τ, level, depth) における pattern_id の top1 クラス情報を返す。"""
    counter: Counter = Counter()
    for mb_id in gp:
        cid = mb_to_class.get(mb_id)
        if cid is not None:
            counter[cid] += 1
    if not counter:
        return {"top1_class_id": "", "class_size": 0, "intersection": 0}
    top_cid, inter = counter.most_common(1)[0]
    class_members = classes.get(top_cid, [])
    return {
        "top1_class_id": top_cid,
        "class_size": len(class_members),
        "intersection": inter,
    }


def main() -> None:
    out_dir = ensure_out_dir()

    rows: list[dict] = []
    repr_dict: dict = {}  # {(τ, level, depth, pid): {...}}

    # 既知パターン正解事例 mb_id 集合を一度キャッシュ
    gt_cache: dict[int, set[int]] = {}
    for pid in KNOWN_PATTERNS:
        gt = load_rq1_ground_truth(pid)
        gt_cache[pid] = {int(r["mb_id"]) for r in gt}

    for tau in TAUS:
        for level in LEVELS:
            for depth in DEPTHS:
                classes = load_classes(tau, level, depth)
                mb_to_class = build_member_to_class(classes, depth)
                mm_reps = load_representative(tau, level, depth, "mode_medoid")

                for pid in KNOWN_PATTERNS:
                    gp = gt_cache[pid]
                    gp_size = len(gp)
                    info = get_top1_for_pattern(tau, level, depth, pid, classes, mb_to_class, gp)
                    cid = info["top1_class_id"]
                    mm = mm_reps.get(cid, {}) if cid else {}
                    rep_value = mm.get("representative", {}).get("value", "") if mm else ""
                    rep_id = mm.get("representative", {}).get("id", "") if mm else ""
                    strategy = mm.get("strategy", "") if mm else ""
                    support = mm.get("support", 0) if mm else 0

                    inter = info["intersection"]
                    class_size = info["class_size"]
                    recall = inter / gp_size if gp_size else 0.0
                    precision = inter / class_size if class_size else 0.0
                    f1 = (2 * recall * precision / (recall + precision)) if (recall + precision) else 0.0

                    rows.append(
                        {
                            "tau": tau,
                            "level": level,
                            "depth": depth,
                            "pattern_id": pid,
                            "pattern_name": PATTERN_NAME[pid],
                            "gp_size": gp_size,
                            "top1_class_id": cid,
                            "class_size": class_size,
                            "intersection": inter,
                            "recall": recall,
                            "precision": precision,
                            "f1": f1,
                            "mode_medoid_strategy": strategy,
                            "mode_medoid_representative_id": rep_id,
                            "mode_medoid_value": rep_value,
                            "mode_medoid_support": support,
                        }
                    )
                    repr_dict[f"{tau}_{level}_{depth}_{pid}"] = rows[-1]

    csv_path = out_dir / "E1_top1_representatives.csv"
    fields = [
        "tau",
        "level",
        "depth",
        "pattern_id",
        "pattern_name",
        "gp_size",
        "top1_class_id",
        "class_size",
        "intersection",
        "recall",
        "precision",
        "f1",
        "mode_medoid_strategy",
        "mode_medoid_representative_id",
        "mode_medoid_value",
        "mode_medoid_support",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[OUTPUT] {csv_path}")

    json_path = out_dir / "E1_top1_representatives.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(repr_dict, f, indent=2, ensure_ascii=False)
    print(f"[OUTPUT] {json_path}")

    # stdout: パターンごとに 16 行 × 7 パターン
    for pid in KNOWN_PATTERNS:
        print(f"\n=== pattern {pid}: {PATTERN_NAME[pid]} (正解数 {len(gt_cache[pid])}) ===")
        print(f"{'τ':>4} {'L':>2} {'depth':>10} | {'top1 class':<22} {'∩/size':>10} {'medoid strategy':>14} {'support':>8} | medoid value")
        for r in rows:
            if r["pattern_id"] != pid:
                continue
            print(
                f"{r['tau']:>4.1f} {r['level']:>2} {r['depth']:>10} | "
                f"{r['top1_class_id']:<22} {r['intersection']:>4}/{r['class_size']:<5} "
                f"{r['mode_medoid_strategy']:>14} {r['mode_medoid_support']:>8} | "
                f"{r['mode_medoid_value']!r:.80}"
            )

    # --- pattern_id ごとに precision > 0 のクラスを JSON で出力 (_precision / _f1 の 2 種) ---
    def _build_nonzero(sort_key: str) -> dict[str, list[dict]]:
        result: dict[str, list[dict]] = {}
        for pid in KNOWN_PATTERNS:
            pid_rows = [
                {
                    "tau": row["tau"],
                    "level": row["level"],
                    "depth": row["depth"],
                    "class_id": row["top1_class_id"],
                    "class_size": row["class_size"],
                    "precision": round(row["precision"], 6),
                    "recall": round(row["recall"], 6),
                    "f1": round(row["f1"], 6),
                    "mode_medoid_strategy": row["mode_medoid_strategy"],
                    "mode_medoid_value": row["mode_medoid_value"],
                    "mode_medoid_support": row["mode_medoid_support"],
                }
                for row in rows
                if row["pattern_id"] == pid and row["precision"] > 0
            ]
            pid_rows.sort(key=lambda x: -x[sort_key])
            result[str(pid)] = pid_rows
        return result

    nonzero_precision = _build_nonzero("precision")
    nonzero_f1 = _build_nonzero("f1")

    prec_path = out_dir / "E1_top1_precision_nonzero_precision.json"
    with prec_path.open("w", encoding="utf-8") as f:
        json.dump(nonzero_precision, f, indent=2, ensure_ascii=False)
    print(f"\n[OUTPUT] {prec_path}")

    f1_path = out_dir / "E1_top1_precision_nonzero_f1.json"
    with f1_path.open("w", encoding="utf-8") as f:
        json.dump(nonzero_f1, f, indent=2, ensure_ascii=False)
    print(f"[OUTPUT] {f1_path}")

    print("\n=== Per-pattern classes with precision > 0 — sorted by precision (desc) ===")
    for pid in KNOWN_PATTERNS:
        entries = nonzero_precision[str(pid)]
        print(f"\n  [pattern_id={pid}]  ({len(entries)} entries)")
        print(json.dumps(entries, indent=4, ensure_ascii=False))

    print("\n=== Per-pattern classes with precision > 0 — sorted by F1 (desc) ===")
    for pid in KNOWN_PATTERNS:
        entries = nonzero_f1[str(pid)]
        print(f"\n  [pattern_id={pid}]  ({len(entries)} entries)")
        print(json.dumps(entries, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    main()
