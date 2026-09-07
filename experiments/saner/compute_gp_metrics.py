r"""正解集合を正解ラベルとしてクラスタを同定し、R_union / R_max / pairwise recall / n_eff を出す。

検出器（matcher）を再適用せず、事前に振られたパターンごとの正解 id をラベルとして使う。
クラスタが ``G_p[p]`` の要素を 1 件以上含めばパターン p のクラスタとみなす（membership 同定）。

算出する 4 指標:
    R_union        : 同定された非孤立クラスタ（size >= 2）の和集合に対する Recall。
    R_max          : 同定された非孤立クラスタのうち最大規模のものに対する Recall。
    pairwise_recall: 同一パターンのペアが同一クラスタに入る割合
                     ``Σ C(TP_i,2) / C(|G_p|,2)``。クラスタ選択を必要としない。
    n_eff          : 実効クラスタ数 ``1 / Σ p_i^2``（``p_i`` は covered G_p 内の TP 比率）。
                     1 なら完全集約、大きいほど分散。``|G_p|`` に依らず比較できる。

正解集合は 2 種を比較する。
    old: outputs/scam/PreAnalysis/matches.jsonl          diff_linked=True
    new: outputs/saner/PreAnalysis/base_only_hits.jsonl  slow 側のみ検出

対象は Parent を除く 12 設定（τ ∈ {0.7, 0.9} × α ∈ {a0, a1} × σ ∈ {s1, s2, s3}）。

入力:
    outputs/scam/PreAnalysis/matches.jsonl                  old G_p
    outputs/saner/PreAnalysis/base_only_hits.jsonl          new G_p
    outputs/scam/approach/integrate/.../{depth}_label.json  クラスタとメンバー

出力:
    outputs/saner/{old,new}_gp/gp_metrics.csv   設定×パターンの 4 指標（正解集合ごとに分割）
    標準出力に可読マトリクス
"""

from __future__ import annotations

import csv
import json

from hayalab.config import PathConfig

# --- 設定軸 -----------------------------------------------------------------
TAUS: list[tuple[str, str]] = [("jaccard07", "0.7"), ("jaccard09", "0.9")]
LEVELS: list[tuple[int, str]] = [(1, "a0"), (2, "a1")]
DEPTHS: list[tuple[str, str]] = [("Diff", "s1"), ("Brother", "s2"), ("ExParent", "s3")]
GP_SOURCES: list[str] = ["old", "new"]


# --- ヘルパ（設定ごとに呼ばれる） -------------------------------------------
def load_members(integrate_dir, tau_dir: str, level: int, depth: str) -> dict[str, list[int]]:
    """1 設定の ``class_id -> メンバー pair id リスト`` を返す。

    Args:
        integrate_dir: integrate 出力のルートディレクトリ。
        tau_dir: 閾値ディレクトリ名（``jaccard07`` 等）。
        level: 抽象化レベル。
        depth: 対象 depth。

    Returns:
        ``{class_id: [pair id, ...]}``。
    """
    label_path = integrate_dir / tau_dir / f"level{level}" / depth / f"{depth}_label.json"
    if not label_path.exists():
        raise FileNotFoundError(f"label not found: {label_path}")
    with label_path.open(encoding="utf-8") as f:
        classes = json.load(f)
    return {cid: [int(r["id"]) for r in rows] for cid, rows in classes.items()}


def load_gp(matches_path, base_only_path) -> dict[str, dict[int, set[int]]]:
    """2 種の正解集合を ``{source: {pattern_id: pair id 集合}}`` で返す。

    Args:
        matches_path: ``matches.jsonl``（``diff_linked`` フラグを持つ）。
        base_only_path: ``base_only_hits.jsonl``。

    Returns:
        ``{"old": {...}, "new": {...}}``。
    """
    out: dict[str, dict[int, set[int]]] = {"old": {}, "new": {}}
    with matches_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("diff_linked") is True:
                out["old"].setdefault(record["target_id"], set()).add(int(record["mb_id"]))
    with base_only_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            out["new"].setdefault(record["target_id"], set()).add(int(record["mb_id"]))
    return out


# --- ヘルパ（設定 × パターンごとに呼ばれる） --------------------------------
def compute_metrics(members_of: dict[str, list[int]], gp_ids: set[int]) -> dict | None:
    """1 設定 × 1 パターンの 4 指標を計算する。

    Args:
        members_of: ``{class_id: メンバー pair id リスト}``。
        gp_ids: 正解集合の pair id 集合。

    Returns:
        指標の辞書。正解要素を含むクラスタが 1 つも無ければ ``None``。
    """
    hits: list[tuple[str, int, int]] = []  # (class_id, tp, size)
    for class_id, ids in members_of.items():
        tp = len(gp_ids.intersection(ids))
        if tp:
            hits.append((class_id, tp, len(ids)))
    covered = sum(tp for _c, tp, _s in hits)
    if covered == 0:
        return None

    union_ids: set[int] = set()
    best_tp = 0
    best_size = -1
    for class_id, tp, size in hits:
        if size < 2:
            continue
        union_ids |= gp_ids.intersection(members_of[class_id])
        if size > best_size:
            best_size = size
            best_tp = tp

    pair_total = len(gp_ids) * (len(gp_ids) - 1) / 2
    pair_hit = sum(tp * (tp - 1) / 2 for _c, tp, _s in hits)
    simpson = sum((tp / covered) ** 2 for _c, tp, _s in hits)
    return {
        "Gp_size": len(gp_ids),
        "coverage": covered / len(gp_ids),
        "n_clusters_with_tp": len(hits),
        "n_isolated": sum(1 for _c, _tp, s in hits if s < 2),
        "R_union": len(union_ids) / len(gp_ids),
        "R_max": best_tp / len(gp_ids),
        "pairwise_recall": pair_hit / pair_total if pair_total else 0.0,
        "n_eff": 1 / simpson if simpson else 0.0,
    }


# --- メインフロー -----------------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    path_config = PathConfig()
    matches_path = path_config.outputs / "scam" / "PreAnalysis" / "matches.jsonl"
    base_only_path = path_config.outputs / "saner" / "PreAnalysis" / "base_only_hits.jsonl"
    integrate_dir = path_config.outputs / "scam" / "approach" / "integrate"
    out_dir = path_config.outputs / "saner"
    out_dir.mkdir(parents=True, exist_ok=True)
    for required in (matches_path, base_only_path, integrate_dir):
        if not required.exists():
            raise FileNotFoundError(f"input not found: {required}")

    # --- Section 2: 正解集合 ---
    gp_all = load_gp(matches_path, base_only_path)
    patterns = sorted({p for table in gp_all.values() for p, ids in table.items() if ids})
    print("評価対象パターン:", patterns, flush=True)
    for source in GP_SOURCES:
        print(f"  {source}: " + str({p: len(gp_all[source].get(p, set())) for p in patterns}), flush=True)

    # --- Section 3: 全設定 × 全パターン × 2 正解集合を算出 ---
    rows: list[dict] = []
    for tau_dir, tau_disp in TAUS:
        for level, alpha_disp in LEVELS:
            for depth, sigma_disp in DEPTHS:
                members_of = load_members(integrate_dir, tau_dir, level, depth)
                for source in GP_SOURCES:
                    for p in patterns:
                        gp_ids = gp_all[source].get(p, set())
                        if not gp_ids:
                            continue
                        metrics = compute_metrics(members_of, gp_ids)
                        if metrics is None:
                            continue
                        rows.append(
                            {
                                "gp_source": source,
                                "tau": tau_disp,
                                "alpha": alpha_disp,
                                "sigma": sigma_disp,
                                "pattern_id": p,
                                **metrics,
                            }
                        )
                print(f"done: {tau_dir}/level{level}/{depth}", flush=True)

    # --- Section 4: 正解集合ごとに CSV 出力 ---
    for source in GP_SOURCES:
        subset = [r for r in rows if r["gp_source"] == source]
        if not subset:
            continue
        source_dir = out_dir / f"{source}_gp"
        source_dir.mkdir(parents=True, exist_ok=True)
        csv_path = source_dir / "gp_metrics.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(subset[0].keys()))
            writer.writeheader()
            writer.writerows(subset)
        print(f"wrote {csv_path} ({len(subset)} 行)", flush=True)

    # --- Section 5: 可読マトリクス（各セル R_union / R_max / pairwiseR / n_eff） ---
    indexed = {(r["gp_source"], r["tau"], r["alpha"], r["sigma"], r["pattern_id"]): r for r in rows}
    for source in GP_SOURCES:
        pats = [p for p in patterns if gp_all[source].get(p)]
        print()
        print(f"=== {source} G_p: R_union / R_max / pairwise_recall / n_eff ===")
        header = " ".join(f"P{p}({len(gp_all[source][p])})".rjust(24) for p in pats)
        print(f"{'tau':>4} {'α':>3} {'σ':>3} {header}")
        for _, tau_disp in TAUS:
            for _, alpha_disp in LEVELS:
                for _, sigma_disp in DEPTHS:
                    cells = []
                    for p in pats:
                        r = indexed.get((source, tau_disp, alpha_disp, sigma_disp, p))
                        cells.append(("--" if r is None else f"{r['R_union']:.2f}/{r['R_max']:.2f}/{r['pairwise_recall']:.3f}/{r['n_eff']:.1f}").rjust(24))
                    print(f"{tau_disp:>4} {alpha_disp:>3} {sigma_disp:>3} " + " ".join(cells))
