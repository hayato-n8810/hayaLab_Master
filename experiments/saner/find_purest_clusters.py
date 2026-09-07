r"""正解集合に対して純度が高い／低いクラスタを、設定・代表値・共通ノードつきで出力する。

各パターンについて設計空間（Parent を除く 12 設定）の全クラスタを走査し、正解要素を
1 件以上含むクラスタを純度 ``TP / size`` で並べる。

    上位 TOP_K: 純度 降順（同値は TP 降順）。パターンを再現できているクラスタ。
    下位 TOP_K: 純度 昇順（同値は規模 降順）。正解要素は含むが希釈されたクラスタ。

各クラスタについて次を出力する。
    設定 (τ / α / σ)、クラスタサイズ、TP、純度、Recall
    代表値: ``select_representatives`` で選んだ REP_K 件（1 件目は既存の代表選択と一致）
    共通ノード: メンバー間で**元の AST**が一致したノードのみを ``anti_unify`` で求め、
                label が ``"name: value [begin,end]"`` 形式の終端ノードを出現順に連結した文字列

ランキングに正解集合を使うため性能の主張には使えない。「設計空間のどこに再現クラスタが
あるか」「どこで希釈されるか」の事後確認として用いる。

正解集合は old (matches.jsonl の diff_linked) / new (base_only_hits.jsonl) の 2 種で、
結果は ``old_gp/`` と ``new_gp/`` に分けて出力する。

入力:
    outputs/scam/PreAnalysis/matches.jsonl                  old G_p
    outputs/saner/PreAnalysis/base_only_hits.jsonl          new G_p
    outputs/scam/approach/integrate/.../{depth}_label.json  クラスタとメンバー value
    outputs/scam/approach/cutouts.json                      具象 cut（punctuation を含む）

出力:
    outputs/saner/{old,new}_gp/purity_extremes.csv   上位／下位クラスタの素データ
    outputs/saner/{old,new}_gp/purity_extremes.md    代表値と共通ノードの目視用
"""

from __future__ import annotations

import csv
import json
import re

import ijson

from hayalab.config import PathConfig
from hayalab.scam.generalize import anti_unify
from hayalab.scam.representative import select_representatives

# --- 設定軸 -----------------------------------------------------------------
TAUS: list[tuple[str, str]] = [("jaccard07", "0.7"), ("jaccard09", "0.9")]
LEVELS: list[tuple[int, str]] = [(1, "a0"), (2, "a1")]
DEPTHS: list[tuple[str, str]] = [("Diff", "s1"), ("Brother", "s2"), ("ExParent", "s3")]
GP_SOURCES: list[str] = ["old", "new"]

# --- 出力の制御 -------------------------------------------------------------
# 対象とするクラスタ規模の下限（size=2 の自明な純度 1.0 を除く）
MIN_SIZE: int = 3
# 上位／下位それぞれ何件出すか
TOP_K: int = 5
# 1 クラスタで描く代表の件数
REP_K: int = 3
# 共通ノードの計算に使うメンバー数の上限（pair id 昇順で切る）
MAX_MEMBERS: int = 20
# value 連結の区切り文字（print_tree.py と同じ）
VALUE_SEPARATOR: str = " "
# 終端ノード判定: ``"name: value [...]"`` 形式の label にマッチ
TERMINAL_LABEL_RE = re.compile(r"([^ ]+): (.+)")


# --- ヘルパ（設定ごとに呼ばれる） -------------------------------------------
def load_setting(integrate_dir, tau_dir: str, level: int, depth: str) -> dict[str, list[dict]]:
    """1 設定の ``class_id -> メンバー行 [{id, value}, ...]`` を返す。

    Args:
        integrate_dir: integrate 出力のルートディレクトリ。
        tau_dir: 閾値ディレクトリ名。
        level: 抽象化レベル。
        depth: 対象 depth。

    Returns:
        ``{class_id: [{"id": int, "value": str}, ...]}``。
    """
    label_path = integrate_dir / tau_dir / f"level{level}" / depth / f"{depth}_label.json"
    if not label_path.exists():
        raise FileNotFoundError(f"label not found: {label_path}")
    with label_path.open(encoding="utf-8") as f:
        classes = json.load(f)
    return {cid: [{"id": int(r["id"]), "value": r["value"]} for r in rows] for cid, rows in classes.items()}


def load_gp(matches_path, base_only_path) -> dict[str, dict[int, set[int]]]:
    """2 種の正解集合を ``{source: {pattern_id: pair id 集合}}`` で返す。

    Args:
        matches_path: ``matches.jsonl``。
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


# --- ヘルパ（クラスタごとに呼ばれる） ---------------------------------------
def common_terminal_text(cuts: list[list[dict]]) -> tuple[str, int]:
    """メンバーの具象 cut から共通ノードを求め、終端ノードの value を連結する。

    Args:
        cuts: メンバーごとの具象 cut ``nodes`` リスト。

    Returns:
        ``(連結テキスト, 共通ノード数)``。cut が無ければ ``("", 0)``。
    """
    if not cuts:
        return "", 0
    generalized = anti_unify(cuts)
    concrete = [g for g in generalized if g["kind"] == "concrete"]
    text = VALUE_SEPARATOR.join(g["value"] for g in concrete if g["value"] and TERMINAL_LABEL_RE.match(g.get("label", "")))
    return text, len(concrete)


# --- メインフロー -----------------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決と正解集合 ---
    path_config = PathConfig()
    matches_path = path_config.outputs / "scam" / "PreAnalysis" / "matches.jsonl"
    base_only_path = path_config.outputs / "saner" / "PreAnalysis" / "base_only_hits.jsonl"
    integrate_dir = path_config.outputs / "scam" / "approach" / "integrate"
    cutouts_path = path_config.outputs / "scam" / "approach" / "cutouts.json"
    out_dir = path_config.outputs / "saner"
    for required in (matches_path, base_only_path, integrate_dir, cutouts_path):
        if not required.exists():
            raise FileNotFoundError(f"input not found: {required}")

    gp_all = load_gp(matches_path, base_only_path)
    patterns = sorted({p for table in gp_all.values() for p, ids in table.items() if ids})
    print("評価対象パターン:", patterns, flush=True)

    # --- Section 2: 全設定を読み込む ---
    settings: list[tuple[str, str, str, str, dict[str, list[dict]]]] = []
    for tau_dir, tau_disp in TAUS:
        for level, alpha_disp in LEVELS:
            for depth, sigma_disp in DEPTHS:
                settings.append((tau_disp, alpha_disp, sigma_disp, depth, load_setting(integrate_dir, tau_dir, level, depth)))
        print(f"loaded: {tau_dir}", flush=True)

    # --- Section 3: 正解集合 × パターンで上位／下位クラスタを選ぶ ---
    selected: list[dict] = []
    for source in GP_SOURCES:
        for p in patterns:
            gp_ids = gp_all[source].get(p, set())
            if not gp_ids:
                continue
            candidates: list[dict] = []
            for tau_disp, alpha_disp, sigma_disp, depth, classes in settings:
                for class_id, members in classes.items():
                    ids = [r["id"] for r in members]
                    if len(ids) < MIN_SIZE:
                        continue
                    tp = len(gp_ids.intersection(ids))
                    if tp == 0:
                        continue
                    candidates.append(
                        {
                            "gp_source": source,
                            "pattern_id": p,
                            "Gp_size": len(gp_ids),
                            "tau": tau_disp,
                            "alpha": alpha_disp,
                            "sigma": sigma_disp,
                            "depth": depth,
                            "class_id": class_id,
                            "size": len(ids),
                            "tp": tp,
                            "purity": tp / len(ids),
                            "recall": tp / len(gp_ids),
                            "n_distinct_values": len({r["value"].strip() for r in members}),
                            "members": sorted(ids)[:MAX_MEMBERS],
                            "all_members": members,
                        }
                    )
            if not candidates:
                continue
            high = sorted(candidates, key=lambda r: (-r["purity"], -r["tp"], r["class_id"]))[:TOP_K]
            low = sorted(candidates, key=lambda r: (r["purity"], -r["size"], r["class_id"]))[:TOP_K]
            for rank, row in enumerate(high, start=1):
                selected.append({**row, "group": "high", "rank": rank})
            for rank, row in enumerate(low, start=1):
                selected.append({**row, "group": "low", "rank": rank})
            print(f"done: {source}/P{p} (候補 {len(candidates)} 件)", flush=True)

    # --- Section 4: 代表を決め、具象 cut を 1 パスで収集 ---
    needed: dict[str, set[int]] = {}
    for row in selected:
        row["reps"] = select_representatives(row["all_members"], {}, REP_K)
        needed.setdefault(row["depth"], set()).update(row["members"])
    all_ids = set().union(*needed.values()) if needed else set()
    concrete: dict[tuple[int, str], list[dict]] = {}
    with cutouts_path.open("rb") as f:
        for entry in ijson.items(f, "item"):
            if entry["id"] not in all_ids:
                continue
            for depth, ids in needed.items():
                if entry["id"] in ids:
                    cut = entry.get("cutouts", {}).get(depth)
                    if cut:
                        concrete[(entry["id"], depth)] = cut.get("nodes", [])
    print(f"[CONCRETE] {len(concrete)} (pair, depth)", flush=True)

    for row in selected:
        cuts = [concrete[(m, row["depth"])] for m in row["members"] if (m, row["depth"]) in concrete]
        row["common_text"], row["n_common_nodes"] = common_terminal_text(cuts)
        row["n_members_used"] = len(cuts)

    # --- Section 5: 正解集合ごとに CSV / Markdown 出力 ---
    fieldnames = [
        "gp_source",
        "group",
        "rank",
        "pattern_id",
        "Gp_size",
        "tau",
        "alpha",
        "sigma",
        "class_id",
        "size",
        "tp",
        "purity",
        "recall",
        "n_distinct_values",
        "n_members_used",
        "n_common_nodes",
        "common_text",
        "rep_id",
        "rep_value",
    ]
    group_label = {"high": f"純度 上位 {TOP_K}", "low": f"純度 下位 {TOP_K}（正解要素は含む）"}

    for source in GP_SOURCES:
        subset = [r for r in selected if r["gp_source"] == source]
        if not subset:
            continue
        source_dir = out_dir / f"{source}_gp"
        source_dir.mkdir(parents=True, exist_ok=True)

        csv_path = source_dir / "purity_extremes.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in subset:
                writer.writerow({**row, "rep_id": row["reps"][0]["id"], "rep_value": row["reps"][0]["value"].strip()})
        print(f"wrote {csv_path} ({len(subset)} 行)", flush=True)

        out: list[str] = []
        out.append(f"# 純度の上位／下位クラスタ（{source} G_p）")
        out.append("")
        out.append(f"Parent を除く 12 設定の全クラスタ（size>={MIN_SIZE}、正解要素を 1 件以上含むもの）を")
        out.append(f"パターンごとに純度 `TP / size` で並べ、上位 {TOP_K} 件と下位 {TOP_K} 件を出した。")
        out.append("")
        out.append(f"共通ノードは**抽象化前の AST** でメンバー間が一致したノードのみ（最大 {MAX_MEMBERS} メンバーで計算）。")
        out.append("")
        for p in patterns:
            rows_p = [r for r in subset if r["pattern_id"] == p]
            if not rows_p:
                continue
            out.append(f"## P{p} (|G_p| = {rows_p[0]['Gp_size']})")
            out.append("")
            for group in ("high", "low"):
                out.append(f"### {group_label[group]}")
                out.append("")
                out.append("| # | 設定 | size | TP | 純度 | Recall | 値種 | 共通ノード数 |")
                out.append("|---|---|---|---|---|---|---|---|")
                for row in [r for r in rows_p if r["group"] == group]:
                    out.append(
                        f"| {row['rank']} | τ{row['tau']}/{row['alpha']}/{row['sigma']} | {row['size']} | "
                        f"{row['tp']} | {row['purity']:.3f} | {row['recall']:.3f} | "
                        f"{row['n_distinct_values']} | {row['n_common_nodes']} |"
                    )
                out.append("")
                for row in [r for r in rows_p if r["group"] == group]:
                    out.append(f"#### {group_label[group]} #{row['rank']} — τ{row['tau']}/{row['alpha']}/{row['sigma']}, size={row['size']}, TP={row['tp']}, 純度={row['purity']:.3f}")
                    out.append("")
                    out.append(f"`class_id = {row['class_id']}`")
                    out.append("")
                    out.append("代表値:")
                    out.append("")
                    for rep in row["reps"]:
                        out.append(f"- rank{rep['rank']} ({rep['strategy']}, id={rep['id']}): `{rep['value'].strip()}`")
                    out.append("")
                    out.append(f"共通ノード（{row['n_common_nodes']} ノード / {row['n_members_used']} メンバー）: " + (f"`{row['common_text']}`" if row["common_text"] else "(共通する終端ノードなし)"))
                    out.append("")

        md_path = source_dir / "purity_extremes.md"
        md_path.write_text("\n".join(out) + "\n", encoding="utf-8")
        print("wrote", md_path, flush=True)
