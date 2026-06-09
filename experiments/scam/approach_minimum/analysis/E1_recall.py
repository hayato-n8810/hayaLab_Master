"""E1: 既知 7 パターンの recall 評価 (recall / precision / F1).

各 (τ, level, depth) × 既知 pattern p について:

  G_p = paper §preanalysis の Stage-B 通過 mb_id 集合（正解）
  M_c = クラス c に属する mb_id 集合
  top_class(p) = argmax_c |G_p ∩ M_c|
  recall(p)    = |G_p ∩ top_class| / |G_p|
  precision(p) = |G_p ∩ top_class| / |top_class|
  F1(p)       = 2·recall·precision / (recall + precision)

集計結果を CSV で保存し、 マクロ平均 F1 が最大の cell を "ベスト設定" として stdout に出力する。

出力:
    analysis/outputs/E1_recall_grid.csv  — 32 cell × 7 pattern の行
    analysis/outputs/E1_best_setting.json — マクロ平均 F1 で並べた cell 上位
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict

from _common import (
    DEPTHS,
    KNOWN_PATTERNS,
    LEVELS,
    TAUS,
    build_member_to_class,
    ensure_out_dir,
    load_classes,
    load_rq1_ground_truth,
)


def _metrics(intersection: int, gp_size: int, total_class_size: int) -> tuple[float, float, float]:
    """recall / precision / F1 を計算する。"""
    recall = intersection / gp_size if gp_size else 0.0
    precision = intersection / total_class_size if total_class_size else 0.0
    f1 = (2 * recall * precision / (recall + precision)) if (recall + precision) else 0.0
    return recall, precision, f1


def compute_cell(tau: float, level: int, depth: str) -> list[dict]:
    """1 cell の 7 pattern について metrics を計算する。

    各 pattern p について 3 種の metric を出す:

    - **top1**: top 1 クラスのみ (従来の top_class_recall / precision / F1)
    - **multi (T=2)**: ∩(c, p) ≥ 2 のクラス群を「再現クラス」とした recall / precision / F1
      → 「同じ pattern 事例が 2 件以上集まったクラス」だけを再現とみなす
    - **all-classes**: G_p が落ちた全クラス (∩≥1) の合算
      → 「巨大クラスへの偶発混入も含めた天井値」

    その他:

    - **n_classes**: pattern p の事例が分散したクラス数
    - **n_classes_T2**: ∩≥2 のクラス数

    Returns:
        rows: 各 dict はメトリクス一式を含む
    """
    classes = load_classes(tau, level, depth)
    mb_to_class = build_member_to_class(classes, depth)
    class_size = {cid: len(members) for cid, members in classes.items()}

    rows: list[dict] = []
    for pid in KNOWN_PATTERNS:
        gt = load_rq1_ground_truth(pid)
        gp = [int(r["mb_id"]) for r in gt]
        gp_size = len(gp)

        seen: Counter = Counter()
        missing = 0
        for mb_id in gp:
            cid = mb_to_class.get(mb_id)
            if cid is None:
                missing += 1
            else:
                seen[cid] += 1

        if not seen:
            rows.append(
                {
                    "tau": tau,
                    "level": level,
                    "depth": depth,
                    "pattern_id": pid,
                    "gp_size": gp_size,
                    "missing": missing,
                    "n_classes": 0,
                    "n_classes_T2": 0,
                    "top1_class_id": "",
                    "top1_class_size": 0,
                    "top1_intersection": 0,
                    "top1_recall": 0.0,
                    "top1_precision": 0.0,
                    "top1_f1": 0.0,
                    "multi_T2_intersection": 0,
                    "multi_T2_total_size": 0,
                    "multi_T2_recall": 0.0,
                    "multi_T2_precision": 0.0,
                    "multi_T2_f1": 0.0,
                    "all_intersection": 0,
                    "all_total_size": 0,
                    "all_recall": 0.0,
                    "all_precision": 0.0,
                    "all_f1": 0.0,
                }
            )
            continue

        # top 1
        top_cid, top_inter = seen.most_common(1)[0]
        top_size = class_size[top_cid]
        s1, p1, f1_top = _metrics(top_inter, gp_size, top_size)

        # multi T=2: ∩≥2 のクラス群
        t2_classes = [(cid, n) for cid, n in seen.items() if n >= 2]
        t2_inter = sum(n for _, n in t2_classes)
        t2_total_size = sum(class_size[cid] for cid, _ in t2_classes)
        s2, p2, f1_t2 = _metrics(t2_inter, gp_size, t2_total_size)

        # all (∩≥1) — 天井
        all_inter = sum(seen.values())
        all_total_size = sum(class_size[cid] for cid in seen)
        sa, pa, f1_a = _metrics(all_inter, gp_size, all_total_size)

        rows.append(
            {
                "tau": tau,
                "level": level,
                "depth": depth,
                "pattern_id": pid,
                "gp_size": gp_size,
                "missing": missing,
                "n_classes": len(seen),
                "n_classes_T2": len(t2_classes),
                "top1_class_id": top_cid,
                "top1_class_size": top_size,
                "top1_intersection": top_inter,
                "top1_recall": s1,
                "top1_precision": p1,
                "top1_f1": f1_top,
                "multi_T2_intersection": t2_inter,
                "multi_T2_total_size": t2_total_size,
                "multi_T2_recall": s2,
                "multi_T2_precision": p2,
                "multi_T2_f1": f1_t2,
                "all_intersection": all_inter,
                "all_total_size": all_total_size,
                "all_recall": sa,
                "all_precision": pa,
                "all_f1": f1_a,
            }
        )
    return rows


def _macro(rows: list[dict], prefix: str) -> tuple[float, float, float]:
    """rows のメトリクス列を抜き出してマクロ平均を返す。"""
    n = len(rows)
    if n == 0:
        return 0.0, 0.0, 0.0
    s = sum(r[f"{prefix}_recall"] for r in rows) / n
    p = sum(r[f"{prefix}_precision"] for r in rows) / n
    f = sum(r[f"{prefix}_f1"] for r in rows) / n
    return s, p, f


def main() -> None:
    out_dir = ensure_out_dir()

    all_rows: list[dict] = []
    cell_macro: list[dict] = []

    for tau in TAUS:
        for level in LEVELS:
            for depth in DEPTHS:
                rows = compute_cell(tau, level, depth)
                all_rows.extend(rows)
                t1_s, t1_p, t1_f = _macro(rows, "top1")
                t2_s, t2_p, t2_f = _macro(rows, "multi_T2")
                a_s, a_p, a_f = _macro(rows, "all")
                cell_macro.append(
                    {
                        "tau": tau,
                        "level": level,
                        "depth": depth,
                        "top1_recall": t1_s,
                        "top1_precision": t1_p,
                        "top1_f1": t1_f,
                        "multi_T2_recall": t2_s,
                        "multi_T2_precision": t2_p,
                        "multi_T2_f1": t2_f,
                        "all_recall": a_s,
                        "all_precision": a_p,
                        "all_f1": a_f,
                    }
                )
                print(
                    f"[τ={tau} L{level} {depth:>8}] top1: s={t1_s:.3f} p={t1_p:.3f} F1={t1_f:.3f}  |  T2: s={t2_s:.3f} p={t2_p:.3f} F1={t2_f:.3f}  |  all: s={a_s:.3f} p={a_p:.3f} F1={a_f:.3f}",
                    flush=True,
                )

    # 詳細 CSV
    csv_path = out_dir / "E1_recall_grid.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "tau",
            "level",
            "depth",
            "pattern_id",
            "gp_size",
            "missing",
            "n_classes",
            "n_classes_T2",
            "top1_class_id",
            "top1_class_size",
            "top1_intersection",
            "top1_recall",
            "top1_precision",
            "top1_f1",
            "multi_T2_intersection",
            "multi_T2_total_size",
            "multi_T2_recall",
            "multi_T2_precision",
            "multi_T2_f1",
            "all_intersection",
            "all_total_size",
            "all_recall",
            "all_precision",
            "all_f1",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in all_rows:
            w.writerow(row)
    print(f"\n[OUTPUT] {csv_path}")

    # ベスト設定 ranking
    # 「再現できた」の主指標として multi_T2_f1 を採用 (top1 は過小、 all は天井)
    cell_macro.sort(key=lambda x: (-x["multi_T2_f1"], -x["multi_T2_recall"]))
    best_path = out_dir / "E1_best_setting.json"
    ranking = [{"rank": i + 1, **cell} for i, cell in enumerate(cell_macro)]
    with best_path.open("w", encoding="utf-8") as f:
        json.dump(ranking, f, indent=2, ensure_ascii=False)
    print(f"[OUTPUT] {best_path}")
    print("\n=== Top 5 cells by macro multi_T2 F1 ===")
    for r in ranking[:5]:
        print(
            f"  #{r['rank']} τ={r['tau']} L{r['level']} {r['depth']:>8} : "
            f"T2 recall={r['multi_T2_recall']:.3f} precision={r['multi_T2_precision']:.3f} "
            f"F1={r['multi_T2_f1']:.3f}  |  top1 F1={r['top1_f1']:.3f}  |  all recall={r['all_recall']:.3f}"
        )

    # --- pattern_id ごとに precision > 0 のクラスを JSON で出力 ---
    precision_nonzero: dict[str, dict[int, list[dict]]] = {}
    for pid in KNOWN_PATTERNS:
        pid_rows = [
            {
                "tau": row["tau"],
                "level": row["level"],
                "depth": row["depth"],
                "class_id": row["top1_class_id"],
                "class_size": row["top1_class_size"],
                "precision": round(row["top1_precision"], 6),
            }
            for row in all_rows
            if row["pattern_id"] == pid and row["top1_precision"] > 0
        ]

        # まず precision で降順にソート
        pid_rows.sort(key=lambda x: -x["precision"])

        # depth ごとにグループ化
        depth_groups = defaultdict(list)
        for row in pid_rows:
            depth_groups[row["depth"]].append(row)

        # defaultdict を通常の dict に戻して代入
        precision_nonzero[str(pid)] = dict(depth_groups)

    nonzero_path = out_dir / "E1_precision_nonzero.json"
    with nonzero_path.open("w", encoding="utf-8") as f:
        json.dump(precision_nonzero, f, indent=2, ensure_ascii=False)
    print(f"[OUTPUT] {nonzero_path}")

    print("\n=== Per-pattern classes with precision > 0 (sorted desc) ===")
    for pid in KNOWN_PATTERNS:
        entries = precision_nonzero[str(pid)]
        print(f"\n  [pattern_id={pid}]  ({len(entries)} entries)")
        print(json.dumps(entries, indent=4, ensure_ascii=False))


if __name__ == "__main__":
    main()
