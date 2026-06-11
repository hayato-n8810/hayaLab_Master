r"""限界L2の定量化: c_p 同定クラスタの非 G_p 要素に占める no_diff_linked の割合。

本文（RQ1 結果・方法論）の主張:
  「c_p 同定クラスタの G_p ではない要素の多くは，低速側に同型構造が現れるが書き換えが
    行われていない事例（事前分析の条件(i)のみ充足＝no_diff_linked）である」
を検証する。

各設計条件・各パターン p について:
  - C            : 代表値が pi_p を満たす非孤立クラスタの和集合（matcher 同定。build_rq1_matrix と同一）
  - G_p          : diff_linked=True（条件(i)かつ(ii)）の pair 集合
  - FP = C \ G_p : 同定クラスタ中の非正解要素
  - FP ∩ NoDiff  : FP のうち no_diff_linked（条件(i)のみ充足）に含まれる pair 数
  - 比率         : |FP ∩ NoDiff| / |FP|
を算出し，fp_no_diff.csv に出力する。標準出力には τ=0.7・α0 の要約を示す。

注意: no_diff_linked は事前分析がサイズ分け前の素コードに対して判定した集合である。
      本スクリプトはそれを「低速側に同型の変更前構造が現れるが書き換えが確認されない
      事例」の集合として参照する（precision 解釈の補助であり，指標の分母には用いない）。

依存: build_rq1_matrix.py（G_p / no_diff / クラスタ読み込み / matcher 同定キャッシュを再利用）
"""

from __future__ import annotations

import csv

from build_rq1_matrix import (
    ALPHAS,
    OUT_DIR,
    SIGMAS,
    TARGET_PATTERNS,
    TAUS,
    build_match_cache,
    collect_rep_ids_per_depth,
    load_ground_truth,
    load_no_diff_linked,
    load_setting,
)


def main() -> None:
    """全16設計条件で FP 中の no_diff_linked 比率を算出し CSV 出力する。"""
    gp = load_ground_truth()
    no_diff = load_no_diff_linked()

    print("building matcher identification cache (one pass over cutouts.json) ...")
    cache = build_match_cache(collect_rep_ids_per_depth())

    rows: list[dict] = []
    for tau_dir, _ in TAUS:
        for level_dir, _ in ALPHAS:
            for depth, _ in SIGMAS:
                parsed = load_setting(tau_dir, level_dir, depth)
                for p in TARGET_PATTERNS:
                    # C: pi_p を満たす非孤立クラスタの和集合
                    c: set[int] = set()
                    for _cid, (ids, rep_id, _rv) in parsed.items():
                        if rep_id is None or len(ids) < 2:
                            continue
                        if p in cache.get((int(rep_id), depth), frozenset()):
                            c |= ids
                    tp = len(gp[p] & c)
                    fp = c - gp[p]
                    fp_nodiff = len(fp & no_diff[p])
                    rows.append(
                        {
                            "tau": tau_dir,
                            "alpha": level_dir,
                            "sigma": depth,
                            "pattern_id": p,
                            "Gp_size": len(gp[p]),
                            "C_size": len(c),
                            "tp": tp,
                            "fp": len(fp),
                            "fp_no_diff": fp_nodiff,
                            "fp_no_diff_ratio": round(fp_nodiff / len(fp), 3) if fp else "",
                        }
                    )
                print(f"done: {tau_dir}/{level_dir}/{depth}")

    out = OUT_DIR / "fp_no_diff.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "tau",
                "alpha",
                "sigma",
                "pattern_id",
                "Gp_size",
                "C_size",
                "tp",
                "fp",
                "fp_no_diff",
                "fp_no_diff_ratio",
            ],
        )
        w.writeheader()
        w.writerows(rows)
    print("wrote", out)

    print("\n=== FP 中の no_diff_linked 比率 (τ=0.7, α0) ===")
    print("sigma     P  | |Gp| | |C| |  tp |  FP | FP∩noDiff | ratio")
    for r in rows:
        if r["tau"] == "jaccard07" and r["alpha"] == "level0":
            print(f"{r['sigma']:9} {r['pattern_id']:>2} | {r['Gp_size']:>3} | {r['C_size']:>4} | {r['tp']:>3} | {r['fp']:>4} | {r['fp_no_diff']:>8} | {r['fp_no_diff_ratio']}")


if __name__ == "__main__":
    main()
