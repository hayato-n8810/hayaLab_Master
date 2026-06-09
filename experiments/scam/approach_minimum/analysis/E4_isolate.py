"""E4: 集約失敗事例の分析 — Isolated と巨大擬似クラスタ.

2 つの 「集約に失敗する」系統を分析する:

(A) **Isolated** = 1 メンバのみのクラス。 希少 bigram を持つため類似閾値を超える相手が居なかった事例。
(B) **巨大擬似クラスタ** = size ≥ 100 で ``common_bigrams.common_count = 0`` のクラス。 bigram が空の事例が
   integrate.py:219-220 の "空集合同士は強制 Jaccard=1.0" で 1 クラスに吸収された擬似集合体。

L0 については bigram cache (``bigrams_level0_n2.pkl``) を読み込んで isolated と clustered の
bigram 集合サイズ・希少度を比較する。 L1-L3 は abstract JSON が巨大なため対象外 (paper 議論は L0 ベース)。

出力:
    outputs/scam/approach_minimum/analysis/E4_isolated_stats.csv  — L0 の各 depth × τ で isolated vs clustered 統計
    outputs/scam/approach_minimum/analysis/E4_pseudo_cluster.csv    — 全 32 cell で size ≥ 100, common_count=0 のクラス
"""

from __future__ import annotations

import csv
import pickle
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    ABSTRACT_DIR,
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


def load_bigram_cache_l0() -> tuple[dict[str, dict[int, frozenset]], dict[str, dict[int, tuple]], dict[str, int]]:
    """L0 の bigram cache pickle (v7 三本立て schema v2) を読み込む。

    Returns:
        ``(bigrams, unigrams, excluded_count)`` の 3 タプル:
        - bigrams: ``{depth: {mb_id: frozenset(bigrams)}}`` — 2 トークン以上
        - unigrams: ``{depth: {mb_id: tuple of tokens}}`` — 1 トークン事例
        - excluded_count: ``{depth: int}`` — 0 トークン事例の depth 別件数
    """
    path = ABSTRACT_DIR / "bigrams_level0_n2.pkl"
    with path.open("rb") as f:
        payload = pickle.load(f)  # noqa: S301 -- ローカル自己生成 cache
    return payload["bigrams"], payload["unigrams"], payload["excluded"]


def percentile(values: list[int], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def isolated_stats_l0(bigram_table: dict[str, dict[int, frozenset]]) -> list[dict]:
    """L0 の各 (τ, depth) で isolated vs clustered の bigram 統計を計算する。"""
    rows: list[dict] = []
    for tau in TAUS:
        for depth in DEPTHS:
            classes = load_classes(tau, 0, depth)
            depth_bg = bigram_table.get(depth, {})

            # corpus 全体の document frequency
            df: dict = {}
            for mb_id, bg in depth_bg.items():
                for tok in bg:
                    df[tok] = df.get(tok, 0) + 1

            # isolated / clustered で bigram 統計を取る
            iso_sz: list[int] = []
            clu_sz: list[int] = []
            iso_avg_df: list[float] = []
            clu_avg_df: list[float] = []
            iso_zero_bg = 0
            clu_zero_bg = 0
            for cid, members in classes.items():
                is_isolated = len(members) == 1
                for m in members:
                    mb_id = int(m.split("_")[0])
                    bg = depth_bg.get(mb_id, frozenset())
                    bg_size = len(bg)
                    if is_isolated:
                        iso_sz.append(bg_size)
                        if bg_size == 0:
                            iso_zero_bg += 1
                        else:
                            iso_avg_df.append(sum(df[t] for t in bg) / bg_size)
                    else:
                        clu_sz.append(bg_size)
                        if bg_size == 0:
                            clu_zero_bg += 1
                        else:
                            clu_avg_df.append(sum(df[t] for t in bg) / bg_size)

            rows.append(
                {
                    "tau": tau,
                    "level": 0,
                    "depth": depth,
                    "n_isolated": len(iso_sz),
                    "n_clustered": len(clu_sz),
                    "iso_bg_zero": iso_zero_bg,
                    "clu_bg_zero": clu_zero_bg,
                    "iso_bg_size_median": percentile(iso_sz, 0.5),
                    "iso_bg_size_p25": percentile(iso_sz, 0.25),
                    "iso_bg_size_p75": percentile(iso_sz, 0.75),
                    "clu_bg_size_median": percentile(clu_sz, 0.5),
                    "clu_bg_size_p25": percentile(clu_sz, 0.25),
                    "clu_bg_size_p75": percentile(clu_sz, 0.75),
                    "iso_avg_df_median": median(iso_avg_df) if iso_avg_df else 0.0,
                    "iso_avg_df_mean": (sum(iso_avg_df) / len(iso_avg_df)) if iso_avg_df else 0.0,
                    "clu_avg_df_median": median(clu_avg_df) if clu_avg_df else 0.0,
                    "clu_avg_df_mean": (sum(clu_avg_df) / len(clu_avg_df)) if clu_avg_df else 0.0,
                }
            )
    return rows


def analyze_unigram_size_transition(tau: float, level: int) -> list[dict]:
    """L0 Diff の U1 クラスメンバが、 サイズを Brother/ExParent/Parent に
    広げたとき、 どのクラス (M2 か U1 か、 あるいは excluded か) に移動するかを集計する。

    各 U1 クラスについて、 メンバ mb_id を他 depth の class_id にマップして
    分散数 (= 何個の異なるクラスに散ったか) と top destination をカウント。
    """
    from collections import Counter as _C

    # ベース: Diff の U1 クラス
    classes_diff = load_classes(tau, level, "Diff")
    # 他 depth の mb_id → class_id 索引
    mb_to_class: dict[str, dict[int, str]] = {}
    for d in ("Brother", "ExParent", "Parent"):
        c = load_classes(tau, level, d)
        mb_to_class[d] = build_member_to_class(c, d)
        # サイズも取っておく
    class_sizes: dict[str, dict[str, int]] = {}
    for d in ("Brother", "ExParent", "Parent"):
        c = load_classes(tau, level, d)
        class_sizes[d] = {cid: len(m) for cid, m in c.items()}

    rows: list[dict] = []
    for cid, members in classes_diff.items():
        if "_U1_" not in cid:
            continue
        mb_ids = [int(m.split("_")[0]) for m in members]
        size = len(mb_ids)
        for d in ("Brother", "ExParent", "Parent"):
            destinations: _C = _C()
            n_excluded = 0
            n_M2 = 0
            n_U1 = 0
            for mb_id in mb_ids:
                cid_other = mb_to_class[d].get(mb_id)
                if cid_other is None:
                    n_excluded += 1
                else:
                    destinations[cid_other] += 1
                    if "_U1_" in cid_other:
                        n_U1 += 1
                    else:
                        n_M2 += 1
            n_dest = len(destinations)
            if destinations:
                top_dest, top_count = destinations.most_common(1)[0]
            else:
                top_dest, top_count = "", 0
            rows.append(
                {
                    "tau": tau,
                    "level": level,
                    "diff_class_id": cid,
                    "diff_size": size,
                    "target_depth": d,
                    "n_destinations": n_dest,
                    "n_M2_destinations": n_M2,
                    "n_U1_destinations": n_U1,
                    "n_excluded": n_excluded,
                    "top_destination_class_id": top_dest,
                    "top_destination_size": class_sizes[d].get(top_dest, 0),
                    "top_destination_count": top_count,
                    "ratio_top": top_count / size if size else 0.0,
                }
            )
    return rows


def analyze_unigram_clusters() -> list[dict]:
    """全 16 cell で U1 (unigram) クラスを列挙、 サイズ・代表トークン・既知由来を集計。

    U1 クラス = `L*_U1_*` 形式。 1 トークン事例の完全一致集約。
    """
    gt: dict[int, set[int]] = {}
    for pid in KNOWN_PATTERNS:
        gt[pid] = {int(r["mb_id"]) for r in load_rq1_ground_truth(pid)}

    rows: list[dict] = []
    for tau in TAUS:
        for level in LEVELS:
            for depth in DEPTHS:
                classes = load_classes(tau, level, depth)
                for cid, members in classes.items():
                    if "_U1_" not in cid:
                        continue
                    mb_ids = {int(m.split("_")[0]) for m in members}
                    n_known = sum(len(mb_ids & gt[pid]) for pid in KNOWN_PATTERNS)
                    rows.append(
                        {
                            "tau": tau,
                            "level": level,
                            "depth": depth,
                            "class_id": cid,
                            "class_size": len(members),
                            "n_known_pattern_events": n_known,
                        }
                    )
    return rows


def collect_pseudo_clusters() -> list[dict]:
    """全 32 cell で size ≥ 100 のクラスを列挙、 common_count を引く。

    擬似クラスタ = common_count = 0 のもの。 既知パターン 7 種のうち何件含まれるかも集計。
    """
    # 既知パターンの mb_id 集合 (target_id ごと)
    gt: dict[int, set[int]] = {}
    for pid in KNOWN_PATTERNS:
        gt[pid] = {int(r["mb_id"]) for r in load_rq1_ground_truth(pid)}

    rows: list[dict] = []
    for tau in TAUS:
        for level in LEVELS:
            for depth in DEPTHS:
                classes = load_classes(tau, level, depth)
                try:
                    common_reps = load_representative(tau, level, depth, "common_bigrams")
                except (FileNotFoundError, ValueError):
                    # v7: common_bigrams 代表値は今回未生成。 common_count は不明扱い
                    common_reps = {}

                for cid, members in classes.items():
                    sz = len(members)
                    if sz < 100:
                        continue
                    cb = common_reps.get(cid, {})
                    common_count = cb.get("common_count")  # None なら未取得
                    mb_ids = {int(m.split("_")[0]) for m in members}
                    # 既知パターン由来の件数
                    known_breakdown = {pid: len(mb_ids & gt[pid]) for pid in KNOWN_PATTERNS}
                    n_known_total = sum(known_breakdown.values())
                    rows.append(
                        {
                            "tau": tau,
                            "level": level,
                            "depth": depth,
                            "class_id": cid,
                            "class_size": sz,
                            "common_count": common_count if common_count is not None else "",
                            "n_known_pattern_events": n_known_total,
                            "ratio_known": n_known_total / sz,
                            **{f"known_p{pid}": known_breakdown[pid] for pid in KNOWN_PATTERNS},
                        }
                    )
    return rows


def main() -> None:
    out_dir = ensure_out_dir()

    print("[INFO] L0 bigram cache をロード中 ...", flush=True)
    bigram_table, unigram_table, excluded_count = load_bigram_cache_l0()
    print(
        f"[INFO] loaded: bigrams Diff={len(bigram_table['Diff'])}, unigrams Diff={len(unigram_table['Diff'])}, excluded Diff={excluded_count['Diff']}",
        flush=True,
    )

    # (A) Isolated vs clustered 統計
    iso_rows = isolated_stats_l0(bigram_table)
    iso_csv = out_dir / "E4_isolated_stats.csv"
    fields = list(iso_rows[0].keys())
    with iso_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in iso_rows:
            w.writerow(r)
    print(f"[OUTPUT] {iso_csv}")

    print("\n=== Isolated vs Clustered (L0) ===")
    print(f"{'τ':>3} {'depth':>10} | {'iso数':>7} {'clu数':>7} | {'iso bg中央':>10} {'clu bg中央':>10} | {'iso df中央':>10} {'clu df中央':>10} | {'iso bg=0':>9} {'clu bg=0':>9}")
    for r in iso_rows:
        print(
            f"{r['tau']:>3.1f} {r['depth']:>10} | "
            f"{r['n_isolated']:>7} {r['n_clustered']:>7} | "
            f"{r['iso_bg_size_median']:>10.0f} {r['clu_bg_size_median']:>10.0f} | "
            f"{r['iso_avg_df_median']:>10.0f} {r['clu_avg_df_median']:>10.0f} | "
            f"{r['iso_bg_zero']:>9} {r['clu_bg_zero']:>9}"
        )

    # (B) 擬似クラスタ candidate
    pseudo_rows = collect_pseudo_clusters()
    pseudo_csv = out_dir / "E4_pseudo_cluster.csv"
    fields_p = list(pseudo_rows[0].keys()) if pseudo_rows else []
    with pseudo_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields_p)
        w.writeheader()
        for r in pseudo_rows:
            w.writerow(r)
    print(f"\n[OUTPUT] {pseudo_csv}")

    # size ≥ 100 のクラス top (既知由来率の低い順 = ノイズらしさ降順)
    rows_by_known_ratio = sorted(pseudo_rows, key=lambda r: r["ratio_known"])
    rows_by_size = sorted(pseudo_rows, key=lambda r: -r["class_size"])
    print(f"\n=== size ≥ 100 のクラス: size 降順 top 15 ===")
    print(f"{'τ':>3} {'L':>2} {'depth':>10} {'class_id':<20} {'size':>5} {'known':>5} {'know%':>5}")
    for r in rows_by_size[:15]:
        print(f"{r['tau']:>3.1f} {r['level']:>2} {r['depth']:>10} {r['class_id']:<20} {r['class_size']:>5} {r['n_known_pattern_events']:>5} {r['ratio_known'] * 100:>4.1f}%")

    print(f"\n=== size ≥ 100 のクラス: 既知由来率 0% で size 降順 top 10 (ノイズ候補) ===")
    noise_candidates = [r for r in rows_by_size if r["n_known_pattern_events"] == 0]
    for r in noise_candidates[:10]:
        print(f"{r['tau']:>3.1f} {r['level']:>2} {r['depth']:>10} {r['class_id']:<20} size={r['class_size']:>5}")

    print(f"\n[summary] size≥100 のクラス: {len(pseudo_rows)} (16 cell 合計)")
    print(f"[summary] うち既知由来 0 件: {len(noise_candidates)}")

    # (C) U1 unigram クラス分析
    u1_rows = analyze_unigram_clusters()
    u1_csv = out_dir / "E4_unigram_clusters.csv"
    if u1_rows:
        fields_u = list(u1_rows[0].keys())
        with u1_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields_u)
            w.writeheader()
            for r in u1_rows:
                w.writerow(r)
        print(f"\n[OUTPUT] {u1_csv}")

        # depth × τ 集計
        from collections import Counter as _C

        agg: dict = {}
        for r in u1_rows:
            k = (r["tau"], r["level"], r["depth"])
            a = agg.setdefault(k, {"n_classes": 0, "n_members": 0, "n_known": 0, "max_size": 0})
            a["n_classes"] += 1
            a["n_members"] += r["class_size"]
            a["n_known"] += r["n_known_pattern_events"]
            a["max_size"] = max(a["max_size"], r["class_size"])
        print("\n=== U1 (unigram) クラスのセル別集計 ===")
        print(f"{'τ':>3} {'L':>2} {'depth':>10} | {'クラス数':>5} {'メンバ計':>5} {'最大':>4} {'既知由来':>5}")
        for (tau, level, depth), a in sorted(agg.items()):
            print(f"{tau:>3.1f} {level:>2} {depth:>10} | {a['n_classes']:>5} {a['n_members']:>5} {a['max_size']:>4} {a['n_known']:>5}")

    # (D) U1 サイズ遷移 (L0 Diff の U1 クラス → Brother/ExParent/Parent への移動先)
    trans_rows: list[dict] = []
    for tau in TAUS:
        for level in LEVELS:
            trans_rows.extend(analyze_unigram_size_transition(tau, level))
    trans_csv = out_dir / "E4_unigram_size_transition.csv"
    if trans_rows:
        fields_t = list(trans_rows[0].keys())
        with trans_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields_t)
            w.writeheader()
            for r in trans_rows:
                w.writerow(r)
        print(f"\n[OUTPUT] {trans_csv}")

        # 集計: 「U1 クラスが他サイズで何個のクラスに分散したか」 の分布
        print("\n=== U1 サイズ遷移: 分散度合いの集計 (τ=0.7, L0 の U1 クラス → 各 depth) ===")
        target_rows = [r for r in trans_rows if r["tau"] == 0.7 and r["level"] == 0]
        from collections import Counter as _C

        for d in ("Brother", "ExParent", "Parent"):
            ds = [r for r in target_rows if r["target_depth"] == d]
            n_classes = len(ds)
            # 1 つにまとまる (n_destinations==1) クラスの数
            n_collapsed_to_one = sum(1 for r in ds if r["n_destinations"] == 1)
            # M2 のみ / U1 のみ / 混在
            n_to_M2_only = sum(1 for r in ds if r["n_U1_destinations"] == 0 and r["n_M2_destinations"] > 0)
            n_to_U1_only = sum(1 for r in ds if r["n_U1_destinations"] > 0 and r["n_M2_destinations"] == 0)
            n_mixed = sum(1 for r in ds if r["n_U1_destinations"] > 0 and r["n_M2_destinations"] > 0)
            # 分散度数分布
            dist = _C(min(r["n_destinations"], 10) for r in ds)
            print(f"\n  ターゲット: L0 Diff U1 → {d} ({n_classes} 個の U1 クラス)")
            print(f"  1 クラスにまとまる: {n_collapsed_to_one}")
            print(f"  M2 のみへ移動: {n_to_M2_only}")
            print(f"  U1 のみへ移動: {n_to_U1_only}")
            print(f"  混在 (M2 と U1): {n_mixed}")
            print(f"  分散数分布 (10 で打ち切り): {sorted(dist.items())}")
            # 例: 大規模 U1 クラスの遷移先 top 3
            big_u1 = sorted(ds, key=lambda r: -r["diff_size"])[:3]
            print(f"  サイズ上位 3 件の遷移詳細:")
            for r in big_u1:
                print(
                    f"    {r['diff_class_id']} (size={r['diff_size']}) → {d} で {r['n_destinations']} 個の dest, "
                    f"top: {r['top_destination_class_id']} (size={r['top_destination_size']}, count={r['top_destination_count']}, ratio={r['ratio_top'] * 100:.0f}%)"
                )


if __name__ == "__main__":
    main()
