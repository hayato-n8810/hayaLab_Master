"""E6: 新規パターン候補 30 件の抽出 (全 16 cell × 30 件 = 480 candidate).

各 (τ ∈ {0.7, 0.9}, level ∈ {0, 1}, depth ∈ {Diff, Brother, ExParent, Parent}) で:
1. 既知 7 パターンの top_class 集合 K を除外
2. K 以外で size ≥ 10 のクラスを size 降順 30 件を candidate に
3. 各 candidate に skeleton + mode_medoid 代表値 + fast 側 AST_HEAD ペアを併記

ユーザ意図: サイズ depth ごとに対応できるパターン構造が異なり、 周辺文脈で意味が変わり得る。
全 cell で網羅的に candidate を抽出し、 サイズ・抽象度別の比較分析を可能にする。

出力:
    outputs/scam/approach_minimum/analysis/E6_novel_candidates.csv  (16 cell × 30 = 480 行)
    outputs/scam/approach_minimum/analysis/E6_novel_representatives.json
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
    load_ast_head,
    load_classes,
    load_representative,
    load_rq1_ground_truth,
    normalize_value,
)


def get_known_top_classes(tau: float, level: int, depth: str, gt_cache: dict[int, set[int]]) -> set[str]:
    """指定 cell の既知 7 パターン top1 クラス ID 集合を返す。"""
    classes = load_classes(tau, level, depth)
    mb_to_class = build_member_to_class(classes, depth)
    out: set[str] = set()
    for pid in KNOWN_PATTERNS:
        gp = gt_cache[pid]
        counter: Counter = Counter()
        for mb_id in gp:
            cid = mb_to_class.get(mb_id)
            if cid is not None:
                counter[cid] += 1
        if counter:
            top_cid, _ = counter.most_common(1)[0]
            out.add(top_cid)
    return out


def head_token_summary(record: dict, max_nodes: int = 8) -> str:
    """AST_HEAD record から先頭ノードを要約文字列にする。"""
    if record is None:
        return "(no head)"
    nodes = record.get("merged", {}).get("nodes", [])[:max_nodes]
    return " ".join(f"{n['name']}:{normalize_value(n.get('value'))}" for n in nodes)


def ai_classify(skeleton: str, sk_support: list[int], mm_value: str, mm_support: int, sz: int) -> str:
    """AI 一次分類 (novel / variant / noise) を簡易ヒューリスティックで割り当てる。"""
    if not skeleton or skeleton == "*" or (sk_support and sz and max(sk_support) / sz < 0.2):
        return "noise"
    if mm_support and sz and mm_support / sz >= 0.5:
        return "variant"
    return "novel"


def main() -> None:
    out_dir = ensure_out_dir()

    # 正解 mb_id 集合キャッシュ
    gt_cache: dict[int, set[int]] = {}
    for pid in KNOWN_PATTERNS:
        gt_cache[pid] = {int(r["mb_id"]) for r in load_rq1_ground_truth(pid)}

    # AST_HEAD を depth ごとにロード (4 ファイル)
    ast_heads: dict[str, dict] = {}
    for d in DEPTHS:
        print(f"[INFO] AST_HEAD {d} をロード中 ...", flush=True)
        ast_heads[d] = load_ast_head(d)

    all_rows: list[dict] = []
    all_repr: dict = {}

    for tau in TAUS:
        for level in LEVELS:
            for depth in DEPTHS:
                print(f"\n[CELL] τ={tau} L{level} {depth}", flush=True)
                classes = load_classes(tau, level, depth)
                skeleton_reps = load_representative(tau, level, depth, "skeleton")
                medoid_reps = load_representative(tau, level, depth, "mode_medoid")
                ast_head = ast_heads[depth]

                known_tops = get_known_top_classes(tau, level, depth, gt_cache)

                # ベスト設定で size ≥ 10、 known_tops 除外、 size 降順 30 件
                candidates: list[tuple[str, list[str]]] = sorted(
                    [(cid, members) for cid, members in classes.items() if len(members) >= 10 and cid not in known_tops],
                    key=lambda x: -len(x[1]),
                )[:30]

                rank = 0
                for cid, members in candidates:
                    rank += 1
                    sz = len(members)
                    mb_ids = sorted([int(m.split("_")[0]) for m in members])

                    sk = skeleton_reps.get(cid, {})
                    skeleton_str = sk.get("skeleton", "")
                    sk_support = sk.get("support_per_token", [])

                    mm = medoid_reps.get(cid, {})
                    mm_strategy = mm.get("strategy", "")
                    mm_value = mm.get("representative", {}).get("value", "") if mm else ""
                    mm_support = mm.get("support", 0) if mm else 0

                    known_breakdown: dict[int, int] = {}
                    for pid in KNOWN_PATTERNS:
                        n = sum(1 for m in mb_ids if m in gt_cache[pid])
                        if n > 0:
                            known_breakdown[pid] = n
                    n_known_total = sum(known_breakdown.values())

                    sample_heads: list[dict] = []
                    for mb_id in mb_ids[:3]:
                        rec = ast_head.get(mb_id)
                        if rec:
                            sample_heads.append(
                                {
                                    "mb_id": mb_id,
                                    "head_tokens": head_token_summary(rec, max_nodes=10),
                                }
                            )

                    ai_label = ai_classify(skeleton_str, sk_support, mm_value, mm_support, sz)

                    row = {
                        "tau": tau,
                        "level": level,
                        "depth": depth,
                        "rank": rank,
                        "class_id": cid,
                        "class_size": sz,
                        "skeleton": skeleton_str[:200],
                        "skeleton_max_support": max(sk_support) if sk_support else 0,
                        "mode_medoid_strategy": mm_strategy,
                        "mode_medoid_value": mm_value[:200],
                        "mode_medoid_support": mm_support,
                        "n_known_pattern_events": n_known_total,
                        "known_breakdown": json.dumps(known_breakdown),
                        "ai_label": ai_label,
                        "manual_label": "",
                        "first_3_mb_ids": ",".join(str(m) for m in mb_ids[:3]),
                    }
                    all_rows.append(row)

                    key = f"{tau}_{level}_{depth}_{cid}"
                    all_repr[key] = {
                        "tau": tau,
                        "level": level,
                        "depth": depth,
                        "rank": rank,
                        "size": sz,
                        "skeleton": skeleton_str,
                        "skeleton_support_per_token": sk_support,
                        "mode_medoid": {"strategy": mm_strategy, "value": mm_value, "support": mm_support},
                        "n_known_total": n_known_total,
                        "known_breakdown": known_breakdown,
                        "sample_heads": sample_heads,
                        "ai_label": ai_label,
                        "all_mb_ids": mb_ids,
                    }

                # cell summary
                cnt = Counter(r["ai_label"] for r in all_rows if r["tau"] == tau and r["level"] == level and r["depth"] == depth)
                print(f"  candidates={len(candidates)}, AI 分類: novel={cnt['novel']} variant={cnt['variant']} noise={cnt['noise']}")

    # CSV 出力
    csv_path = out_dir / "E6_novel_candidates.csv"
    fields = [
        "tau",
        "level",
        "depth",
        "rank",
        "class_id",
        "class_size",
        "skeleton",
        "skeleton_max_support",
        "mode_medoid_strategy",
        "mode_medoid_value",
        "mode_medoid_support",
        "n_known_pattern_events",
        "known_breakdown",
        "ai_label",
        "manual_label",
        "first_3_mb_ids",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in all_rows:
            w.writerow(r)
    print(f"\n[OUTPUT] {csv_path}  ({len(all_rows)} 行)")

    # JSON 出力
    json_path = out_dir / "E6_novel_representatives.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(all_repr, f, indent=2, ensure_ascii=False)
    print(f"[OUTPUT] {json_path}  ({len(all_repr)} entries)")

    # 全 cell 集計
    print("\n=== 16 cell × 30 candidate の AI 一次分類集計 ===")
    print(f"{'τ':>3} {'L':>2} {'depth':>10} | {'novel':>5} {'variant':>7} {'noise':>5}")
    for tau in TAUS:
        for level in LEVELS:
            for depth in DEPTHS:
                cnt = Counter(r["ai_label"] for r in all_rows if r["tau"] == tau and r["level"] == level and r["depth"] == depth)
                print(f"{tau:>3.1f} {level:>2} {depth:>10} | {cnt['novel']:>5} {cnt['variant']:>7} {cnt['noise']:>5}")


if __name__ == "__main__":
    main()
