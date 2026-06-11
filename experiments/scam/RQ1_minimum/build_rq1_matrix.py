r"""RQ1: 既知の高速化パターンが設計空間のどこで「まとまったクラスタ」として
捉えられるかを評価する。

旧来の「正解集合 G_p に対する F1 が最大となるクラスタを事後選択して報告する」
設計は、(a) どのクラスタがパターン p かを G_p で選び、(b) どの設定を見せるかを
G_p で選ぶ、という二重のオラクル（リーク）を含む。本スクリプトは「選択（同定）」と
「評価（採点）」を分離し、同定に G_p を用いない。

同定方式は 2 つ用意する（既定は matcher）:
  - matcher（既定）: クラスタ代表値の元 cut（部分木）に，事前分析と同一の matcher を
    検出ロジック無改変で適用し，変更前構造が cut に存在するかで同定する
    （identify_matcher.py）。AST 構造を用いるため字句近似より厳密。
  - lexical: 代表値（抽象化後トークン列）に対する署名述語 pi_predicate で同定する近似版。
    比較用に残す。

評価（採点）は同定したクラスタに対してのみ G_p（diff_linked=True）で行う。
設定は選ばず全16設定 (τ×α×σ) を行として報告する。

各設計条件・各パターンについて 2 つの Recall を報告する:
  - R_union (recall_noniso): 同定された非孤立クラスタの和集合に対する Recall（局所化）。
  - R_max   (recall_best)  : 同定された最大の単一クラスタに対する Recall（集約のまとまり）。
Precision は補助指標（G_p が下限のため純度として解釈しない）。

入力:
  - outputs/scam/PreAnalysis/matches.jsonl                 G_p (diff_linked=True)
  - outputs/scam/approach_minimum/cutouts.json             各 pair の depth 別 cut（matcher 同定用）
  - outputs/scam/approach_minimum/integrate/
        jaccard{07,09}/level{0,1}/{Diff,Brother,Parent,ExParent}/
          {depth}.json                       classes: class_id -> [ "{id}_{depth}" ]
          {depth}_pattern_mode_medoid.json    classes: class_id -> {representative:{id,value}}

出力 (このスクリプトと同じディレクトリ):
  - rq1_matrix.csv      全設定×全パターンの recall/precision/同定フラグ 等の素データ
  - rq1_matrix.tex      新 Table II: 16設定×7パターンの Recall マトリクス

注: no_diff_linked.jsonl は G_p に含めない（条件(ii)未充足＝偶発一致候補で正解に不適）。
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import ijson
from identify_matcher import match_patterns_on_cut

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[3]
PRE_MATCHES = ROOT / "outputs/scam/PreAnalysis/matches.jsonl"
INTEGRATE = ROOT / "outputs/scam/approach_minimum/integrate"
CUTOUTS = ROOT / "outputs/scam/approach_minimum/cutouts.json"
OUT_DIR = ROOT / "outputs/scam/RQ1_minimum/"
# ---------------------------------------------------------------------------
# 設定軸の定義
# ---------------------------------------------------------------------------
TAUS = [("jaccard07", "0.7"), ("jaccard09", "0.9")]
ALPHAS = [("level0", r"$\alpha_0$"), ("level1", r"$\alpha_1$")]
SIGMAS = [
    ("Diff", r"$\sigma_1$"),
    ("Brother", r"$\sigma_2$"),
    ("ExParent", r"$\sigma_3$"),
    ("Parent", r"$\sigma_4$"),
]

# 評価対象パターン（事前分析で diff_linked が1件以上得られた7種）
TARGET_PATTERNS = [1, 2, 3, 6, 7, 8, 9]


# ---------------------------------------------------------------------------
# lexical 同定（比較用）: 代表値トークン列に対する署名述語
# ---------------------------------------------------------------------------
def pi_predicate(pattern_id: int, rep_value: str) -> bool:
    """変更前構造の字句署名（lexical 同定用）。G_p は参照しない。"""
    t = rep_value.split()
    s = set(t)
    if pattern_id == 1:
        return "hasOwnProperty" in s and "in" in s
    if pattern_id == 2:
        return "substr" in s
    if pattern_id == 3:
        return "String" in s and "new" not in s and "instanceof" not in s
    if pattern_id == 6:
        return "split" in s
    if pattern_id == 7:
        return "toString" in s and "call" in s
    if pattern_id == 8:
        allowed = {"%", "2", "===", "==", "0", "1"}
        if "%" not in s or "2" not in s:
            return False
        return all(tok.startswith("$") or tok in allowed for tok in t)
    if pattern_id == 9:
        return "reduce" in s
    raise ValueError(f"unknown pattern_id={pattern_id}")


# ---------------------------------------------------------------------------
# 正解集合 G_p（diff_linked=True のみ）
# ---------------------------------------------------------------------------
def load_ground_truth() -> dict[int, set[int]]:
    """正解集合 G_p（diff_linked=True の pair id 集合）をパターン別に返す。"""
    gp: dict[int, set[int]] = defaultdict(set)
    with PRE_MATCHES.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("diff_linked") is True:
                gp[r["target_id"]].add(int(r["mb_id"]))
    return {p: gp.get(p, set()) for p in TARGET_PATTERNS}


def load_no_diff_linked() -> dict[int, set[int]]:
    """Precision 解釈補助用の no_diff_linked 集合を返す（G_p には含めない）。"""
    out: dict[int, set[int]] = {p: set() for p in TARGET_PATTERNS}
    with PRE_MATCHES.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("diff_linked") is False and r["target_id"] in out:
                out[r["target_id"]].add(int(r["mb_id"]))
    return out


# ---------------------------------------------------------------------------
# 1設定のクラスタ・代表値（id と value）を読み込む
# ---------------------------------------------------------------------------
def load_setting(tau_dir: str, level_dir: str, depth: str):
    """class_id -> (member id 集合, 代表値の pair id, 代表値文字列) を返す。"""
    base = INTEGRATE / tau_dir / level_dir / depth
    with (base / f"{depth}.json").open() as f:
        classes = json.load(f)["classes"]
    with (base / f"{depth}_pattern_mode_medoid.json").open() as f:
        medoid = json.load(f)["classes"]

    parsed: dict[str, tuple[set[int], int | None, str]] = {}
    for cid, members in classes.items():
        ids = {int(m.rsplit("_", 1)[0]) for m in members}
        rep = medoid.get(cid, {}).get("representative", {})
        rep_id = rep.get("id") if isinstance(rep, dict) else None
        rep_value = rep.get("value", "") if isinstance(rep, dict) else ""
        parsed[cid] = (ids, rep_id, rep_value)
    return parsed


# ---------------------------------------------------------------------------
# matcher 同定: 代表値 pair id × depth ごとに、cut へ matcher を流した結果をキャッシュ
# ---------------------------------------------------------------------------
def collect_rep_ids_per_depth() -> dict[str, set[int]]:
    """全16設定の medoid から、depth 別に必要な代表 pair id を集める。"""
    needed: dict[str, set[int]] = {d: set() for d, _ in SIGMAS}
    for tau_dir, _ in TAUS:
        for level_dir, _ in ALPHAS:
            for depth, _ in SIGMAS:
                path = INTEGRATE / tau_dir / level_dir / depth / f"{depth}_pattern_mode_medoid.json"
                with path.open() as f:
                    cl = json.load(f)["classes"]
                for c in cl.values():
                    rid = c.get("representative", {}).get("id")
                    if rid is not None:
                        needed[depth].add(int(rid))
    return needed


def build_match_cache(needed: dict[str, set[int]]) -> dict[tuple[int, str], frozenset[int]]:
    """cutouts.json を 1 パスで走査し、(pair id, depth) -> 検出パターン id 集合 を作る。"""
    all_ids: set[int] = set().union(*needed.values()) if needed else set()
    cache: dict[tuple[int, str], frozenset[int]] = {}
    done = 0
    with CUTOUTS.open("rb") as f:
        for it in ijson.items(f, "item"):
            i = it["id"]
            if i not in all_ids:
                continue
            cuts = it["cutouts"]
            for depth, ids in needed.items():
                if i in ids and depth in cuts:
                    nodes = cuts[depth].get("nodes", [])
                    cache[(i, depth)] = frozenset(match_patterns_on_cut(nodes))
            done += 1
            if done % 2000 == 0:
                print(f"  match cache: {done}/{len(all_ids)} pairs")
    print(f"  match cache built: {done} pairs, {len(cache)} (id,depth) entries")
    return cache


# ---------------------------------------------------------------------------
# 1設定×1パターンの評価
# ---------------------------------------------------------------------------
def evaluate(parsed, gp_ids: set[int], satisfy):
    """satisfy(cid)->bool で同定したクラスタ集合に対し recall/precision を計算する。

    R_union（非孤立クラスタの和集合）と R_max（最大単一クラスタ）の双方を返す。
    """
    matched_all: set[int] = set()
    matched_noniso: set[int] = set()
    n_all = 0
    n_noniso = 0
    best_ids: set[int] = set()
    best_size = -1
    for cid, (ids, _rid, _rv) in parsed.items():
        if not satisfy(cid):
            continue
        n_all += 1
        matched_all |= ids
        if len(ids) >= 2:
            n_noniso += 1
            matched_noniso |= ids
            if len(ids) > best_size:
                best_size = len(ids)
                best_ids = ids

    def rp(cluster: set[int]):
        tp = len(gp_ids & cluster)
        recall = tp / len(gp_ids) if gp_ids else 0.0
        precision = tp / len(cluster) if cluster else 0.0
        return tp, recall, precision

    tp_a, rec_a, prec_a = rp(matched_all)
    tp_n, rec_n, prec_n = rp(matched_noniso)
    tp_b, rec_b, prec_b = rp(best_ids)
    return {
        "pi_satisfied": n_all > 0,
        "n_pi_clusters_all": n_all,
        "n_pi_clusters_noniso": n_noniso,
        "C_size_all": len(matched_all),
        "C_size_noniso": len(matched_noniso),
        "best_cluster_size": max(best_size, 0),
        "tp_all": tp_a,
        "tp_noniso": tp_n,
        "tp_best": tp_b,
        "recall_all": rec_a,
        "recall_noniso": rec_n,
        "recall_best": rec_b,
        "precision_all": prec_a,
        "precision_noniso": prec_n,
        "precision_best": prec_b,
    }


# ---------------------------------------------------------------------------
# LaTeX 表生成（16設定 × 7パターンの R_union/R_max マトリクス）
# ---------------------------------------------------------------------------
def fmt_cell_dual(row: dict) -> str:
    r"""LaTeX セル ``R_union/R_max``。同定された非孤立クラスタが無ければ ``--``。"""
    if not row["pi_satisfied"] or row["n_pi_clusters_noniso"] == 0:
        return r"\multicolumn{1}{c}{--}"
    return f"{row['recall_noniso']:.2f}/{row['recall_best']:.2f}"


def build_latex(rows: list[dict], gp_sizes: dict[int, int], method: str) -> str:
    """16設定×7パターンの Recall マトリクス（Table II）の LaTeX 文字列を生成する。"""
    by_setting: dict[tuple, dict[int, dict]] = defaultdict(dict)
    for r in rows:
        by_setting[(r["tau"], r["alpha"], r["sigma"])][r["pattern_id"]] = r

    ident = "事前分析と同一の matcher を代表値の元 cut（部分木）に適用して同定する" if method == "matcher" else "代表値トークンの署名述語 $\\pi_p$ で同定する"
    lines = []
    lines.append(r"\begin{table*}[t]")
    lines.append(r"  \centering")
    lines.append(
        r"  \caption{全16設計条件における既知パターンの Recall マトリクス。"
        r"各列は事前分析で diff-link された正解集合 $G_p$（括弧内は $|G_p|$）に対応する。"
        r"各セルは $R_{\cup}/R_{\max}$ を示す: $R_{\cup}$ は同定された非孤立クラスタの"
        r"和集合に対する Recall（局所化の度合い），$R_{\max}$ は同定された最大単一クラスタに"
        r"対する Recall（単一クラスタへの集約の度合い）。``--'' は同定された非孤立クラスタが"
        r"得られなかった設定。クラスタの同定は $G_p$ を参照せず，" + ident + r"（事後 F1 最大選択を用いない）。}"
    )
    lines.append(r"  \label{tab:exp-pattern-best}")
    lines.append(r"  \footnotesize")
    lines.append(r"  \setlength{\tabcolsep}{4pt}")
    header_ids = " & ".join(rf"\makecell{{P{p}\\({gp_sizes[p]})}}" for p in TARGET_PATTERNS)
    lines.append(r"  \begin{tabular}{c c c " + "c " * len(TARGET_PATTERNS) + "}")
    lines.append(r"    \toprule")
    lines.append(r"    $\tau$ & $\alpha$ & $\sigma$ & " + header_ids + r" \\")
    lines.append(r"    \midrule")
    for tau_dir, tau_disp in TAUS:
        for level_dir, a_disp in ALPHAS:
            for depth, s_disp in SIGMAS:
                rmap = by_setting[(tau_dir, level_dir, depth)]
                cells = " & ".join(fmt_cell_dual(rmap[p]) for p in TARGET_PATTERNS)
                lines.append(f"    {tau_disp} & {a_disp} & {s_disp} & {cells} " + r"\\")
        lines.append(r"    \midrule")
    if lines[-1] == r"    \midrule":
        lines[-1] = r"    \bottomrule"
    else:
        lines.append(r"    \bottomrule")
    lines.append(r"  \end{tabular}")
    lines.append(r"\end{table*}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
def main():
    """全16設定×7パターンを評価し、CSV と Table II(LaTeX) を出力する。"""
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--method",
        default="matcher",
        choices=["matcher", "lexical"],
        help="クラスタ同定方式（既定: matcher＝cut部分木へmatcherを流す）",
    )
    args = ap.parse_args()

    gp = load_ground_truth()
    gp_sizes = {p: len(gp[p]) for p in TARGET_PATTERNS}
    print("method:", args.method)
    print("G_p sizes (diff_linked):", gp_sizes)

    match_cache: dict[tuple[int, str], frozenset[int]] = {}
    if args.method == "matcher":
        print("collecting representative ids per depth ...")
        needed = collect_rep_ids_per_depth()
        print({d: len(s) for d, s in needed.items()})
        print("building match cache by streaming cutouts.json (one pass) ...")
        match_cache = build_match_cache(needed)

    rows: list[dict] = []
    for tau_dir, tau_disp in TAUS:
        for level_dir, a_disp in ALPHAS:
            for depth, s_disp in SIGMAS:
                parsed = load_setting(tau_dir, level_dir, depth)
                for p in TARGET_PATTERNS:
                    if args.method == "matcher":

                        def satisfy(cid, _p=p, _depth=depth, _parsed=parsed):
                            rid = _parsed[cid][1]
                            if rid is None:
                                return False
                            return _p in match_cache.get((int(rid), _depth), frozenset())
                    else:

                        def satisfy(cid, _p=p, _parsed=parsed):
                            return pi_predicate(_p, _parsed[cid][2])

                    res = evaluate(parsed, gp[p], satisfy)
                    rows.append(
                        {
                            "tau": tau_dir,
                            "alpha": level_dir,
                            "sigma": depth,
                            "pattern_id": p,
                            "Gp_size": gp_sizes[p],
                            **res,
                        }
                    )
                print(f"done: {tau_dir}/{level_dir}/{depth}")

    # CSV
    csv_path = OUT_DIR / "rq1_matrix.csv"
    fieldnames = [
        "tau",
        "alpha",
        "sigma",
        "pattern_id",
        "Gp_size",
        "pi_satisfied",
        "n_pi_clusters_all",
        "n_pi_clusters_noniso",
        "C_size_all",
        "C_size_noniso",
        "best_cluster_size",
        "tp_all",
        "tp_noniso",
        "tp_best",
        "recall_all",
        "recall_noniso",
        "recall_best",
        "precision_all",
        "precision_noniso",
        "precision_best",
    ]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print("wrote", csv_path)

    # LaTeX
    tex = build_latex(rows, gp_sizes, args.method)
    (OUT_DIR / "rq1_matrix.tex").write_text(tex)
    print("wrote", OUT_DIR / "rq1_matrix.tex")

    # コンソール可読マトリクス
    print(f"\n=== Recall matrix ({args.method})  R_union/R_max  ('--'=no identified non-iso cluster) ===")
    print("tau       alpha  sigma     " + "      ".join(f"P{p}" for p in TARGET_PATTERNS))
    by_setting = defaultdict(dict)
    for r in rows:
        by_setting[(r["tau"], r["alpha"], r["sigma"])][r["pattern_id"]] = r
    for tau_dir, _ in TAUS:
        for level_dir, _ in ALPHAS:
            for depth, _ in SIGMAS:
                rmap = by_setting[(tau_dir, level_dir, depth)]
                cells = []
                for p in TARGET_PATTERNS:
                    rr = rmap[p]
                    if not rr["pi_satisfied"] or rr["n_pi_clusters_noniso"] == 0:
                        cells.append("    --   ")
                    else:
                        cells.append(f"{rr['recall_noniso']:.2f}/{rr['recall_best']:.2f}")
                print(f"{tau_dir:9} {level_dir:6} {depth:9} " + " ".join(cells))


if __name__ == "__main__":
    main()
