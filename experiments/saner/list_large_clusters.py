r"""指定した設定について、要素数の多いクラスタとその代表値を出力する。

対象設定は τ0.7 / α0 の σ1 (Diff) / σ2 (Brother) / σ3 (ExParent)。各 depth の全クラスタを
規模降順に並べ、上位 TOP_N 件について代表値を抽象化済み AST の木として描く。

代表値の選択は ``select_representatives``（1 件目は既存 ``representative_for_class`` と一致、
2 件目以降は bigram-Jaccard 中心性の降順で value が異なるものを追加）。

各クラスタには正解集合との対応を注記する。正解要素を 1 件も含まないクラスタが
新規パターンの候補になる。規模のランキング自体は正解集合に依存しないが、注記が
異なるため結果を ``old_gp/`` と ``new_gp/`` に分けて出力する。

入力:
    outputs/scam/PreAnalysis/matches.jsonl                  old G_p
    outputs/saner/PreAnalysis/base_only_hits.jsonl          new G_p
    outputs/scam/approach/integrate/.../{depth}_label.json  クラスタとメンバー value
    outputs/scam/approach/abstract/abstract_level{L}.json   抽象化済み cut

出力:
    outputs/saner/{old,new}_gp/large_clusters.csv          全 depth のクラスタ規模ランキング
    outputs/saner/{old,new}_gp/large_clusters_{sigma}.md   上位クラスタの代表値（木）
"""

from __future__ import annotations

import csv
import json

import ijson

from hayalab.config import PathConfig
from hayalab.scam.representative import select_representatives

# --- 対象設定 ---------------------------------------------------------------
TAU_DIR: str = "jaccard07"
TAU_DISP: str = "0.7"
LEVEL: int = 1
ALPHA_DISP: str = "a0"
DEPTHS: list[tuple[str, str]] = [("Diff", "s1"), ("Brother", "s2"), ("ExParent", "s3")]
GP_SOURCES: list[str] = ["old", "new"]

# --- 出力の制御 -------------------------------------------------------------
# ランキング対象とするクラスタ規模の下限
MIN_SIZE: int = 3
# 代表値を描くクラスタ数
TOP_N: int = 30
# 1 クラスタで描く代表の件数
REP_K: int = 3
# 木 1 本あたりの最大表示ノード数
MAX_NODES: int = 60


# --- ヘルパ（設定ごとに呼ばれる） -------------------------------------------
def load_setting(integrate_dir, depth: str) -> dict[str, list[dict]]:
    """1 設定の ``class_id -> メンバー行 [{id, value}, ...]`` を返す。

    Args:
        integrate_dir: integrate 出力のルートディレクトリ。
        depth: 対象 depth。

    Returns:
        ``{class_id: [{"id": int, "value": str}, ...]}``。
    """
    label_path = integrate_dir / TAU_DIR / f"level{LEVEL}" / depth / f"{depth}_label.json"
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


# --- ヘルパ（代表ごとに呼ばれる） -------------------------------------------
def render_cut(nodes: list[dict]) -> list[str]:
    """抽象化済み cut をインデント付きの木として描画する。

    深さは ``parent``（root からの祖先 index パス）のうち cut 内に残っている数で決める。

    Args:
        nodes: cutout の ``nodes`` リスト。

    Returns:
        描画行のリスト。行頭 ``*`` は ``variadic=true``。
    """
    present = {n["origin_index"] for n in nodes}
    ordered = sorted(nodes, key=lambda n: n["origin_index"])
    lines: list[str] = []
    for node in ordered[:MAX_NODES]:
        depth = sum(1 for a in node.get("parent") or [] if a in present)
        value = node.get("value") or ""
        shown = f"  {value}" if ":" in node.get("label", "") and value else ""
        marker = "*" if node.get("variadic") else " "
        lines.append(f"{marker} {'  ' * depth}{node['name']}{shown}")
    if len(ordered) > MAX_NODES:
        lines.append(f"  ... 他 {len(ordered) - MAX_NODES} ノード")
    return lines


# --- メインフロー -----------------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    path_config = PathConfig()
    matches_path = path_config.outputs / "scam" / "PreAnalysis" / "matches.jsonl"
    base_only_path = path_config.outputs / "saner" / "PreAnalysis" / "base_only_hits.jsonl"
    integrate_dir = path_config.outputs / "scam" / "approach" / "integrate"
    abstract_path = path_config.outputs / "scam" / "approach" / "abstract" / f"abstract_level{LEVEL}.json"
    out_dir = path_config.outputs / "saner"
    out_dir.mkdir(parents=True, exist_ok=True)
    for required in (matches_path, base_only_path, integrate_dir, abstract_path):
        if not required.exists():
            raise FileNotFoundError(f"input not found: {required}")
    print(f"[SETTING] τ{TAU_DISP} / {ALPHA_DISP} / level{LEVEL}, depths={[d for d, _ in DEPTHS]}", flush=True)

    # --- Section 2: 正解集合（2 種） ---
    gp_all = load_gp(matches_path, base_only_path)
    patterns = sorted({p for table in gp_all.values() for p, ids in table.items() if ids})
    print("評価対象パターン:", patterns, flush=True)

    # --- Section 3: depth ごとに規模降順ランキングを作り、代表を決める ---
    ranking_rows: list[dict] = []
    tops_of: dict[str, list[dict]] = {}
    classes_of: dict[str, dict[str, list[dict]]] = {}
    reps_of: dict[tuple[str, str], list[dict]] = {}
    needed: dict[str, set[int]] = {}

    for depth, sigma_disp in DEPTHS:
        classes = load_setting(integrate_dir, depth)
        classes_of[depth] = classes
        ranking: list[dict] = []
        for class_id, members in classes.items():
            ids = [r["id"] for r in members]
            if len(ids) < MIN_SIZE:
                continue
            row = {
                "sigma": sigma_disp,
                "depth": depth,
                "class_id": class_id,
                "size": len(ids),
                "n_distinct_values": len({r["value"].strip() for r in members}),
            }
            for source in GP_SOURCES:
                hit_patterns = [p for p in patterns if gp_all[source].get(p, set()).intersection(ids)]
                row[f"{source}_gp_patterns"] = " ".join(str(p) for p in hit_patterns)
                row[f"{source}_gp_tp"] = sum(len(gp_all[source].get(p, set()).intersection(ids)) for p in hit_patterns)
                row[f"{source}_is_new_candidate"] = not hit_patterns
            ranking.append(row)
        ranking.sort(key=lambda r: (-r["size"], r["class_id"]))
        ranking_rows.extend(ranking)
        tops_of[depth] = ranking[:TOP_N]
        print(
            f"[{sigma_disp}] {len(classes)} クラスタ / size>={MIN_SIZE} は {len(ranking)} 件 / "
            + " / ".join(f"{s} 新規候補 {sum(1 for r in tops_of[depth] if r[f'{s}_is_new_candidate'])} 件" for s in GP_SOURCES),
            flush=True,
        )
        for row in tops_of[depth]:
            reps = select_representatives(classes[row["class_id"]], {}, REP_K)
            reps_of[(depth, row["class_id"])] = reps
            needed.setdefault(depth, set()).update(r["id"] for r in reps)

    for source in GP_SOURCES:
        source_dir = out_dir / f"{source}_gp"
        source_dir.mkdir(parents=True, exist_ok=True)
        common = ["sigma", "depth", "class_id", "size", "n_distinct_values"]
        fields = common + [f"{source}_gp_patterns", f"{source}_gp_tp", f"{source}_is_new_candidate"]
        csv_path = source_dir / "large_clusters.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(ranking_rows)
        print(f"wrote {csv_path} ({len(ranking_rows)} 行)", flush=True)

    # --- Section 4: 代表の抽象化済み cut を 1 パスで収集 ---
    all_ids = set().union(*needed.values())
    abstract_nodes: dict[tuple[int, str], list[dict]] = {}
    with abstract_path.open("rb") as f:
        for entry in ijson.items(f, "item"):
            if entry["id"] not in all_ids:
                continue
            for depth, ids in needed.items():
                if entry["id"] in ids:
                    cut = entry.get("cutouts", {}).get(depth)
                    if cut:
                        abstract_nodes[(entry["id"], depth)] = cut.get("nodes", [])
    print(f"[ABSTRACT] {len(abstract_nodes)} (pair, depth)", flush=True)

    # --- Section 5: 正解集合 × depth ごとに Markdown 出力 ---
    for source in GP_SOURCES:
        for depth, sigma_disp in DEPTHS:
            out: list[str] = []
            out.append(f"# 要素数の多いクラスタとその代表値（{source} G_p / τ{TAU_DISP} / {ALPHA_DISP} / {sigma_disp} = {depth}）")
            out.append("")
            out.append(f"設定 `{TAU_DIR} / level{LEVEL} / {depth}` の全 {len(classes_of[depth])} クラスタのうち")
            out.append(f"size>={MIN_SIZE} の件数を規模降順に並べ、上位 {TOP_N} 件の代表値を描いた。")
            out.append("")
            out.append("`G_p` 欄が空のクラスタが**新規パターン候補**。木の行頭 `*` は `variadic=true`。")
            out.append("")
            out.append("| # | class_id | size | 値種 | G_p | TP |")
            out.append("|---|---|---|---|---|---|")
            for rank, row in enumerate(tops_of[depth], start=1):
                hits = row[f"{source}_gp_patterns"]
                gp_cell = ("P" + hits.replace(" ", " P")) if hits else "**新規候補**"
                out.append(f"| {rank} | `{row['class_id']}` | {row['size']} | {row['n_distinct_values']} | {gp_cell} | {row[f'{source}_gp_tp']} |")
            out.append("")

            for rank, row in enumerate(tops_of[depth], start=1):
                hits = row[f"{source}_gp_patterns"]
                gp_label = f"P{hits.replace(' ', ' P')} (TP={row[f'{source}_gp_tp']})" if hits else "新規候補"
                out.append(f"## #{rank} `{row['class_id']}` — size={row['size']}, 値種 {row['n_distinct_values']} — {gp_label}")
                out.append("")
                for rep in reps_of[(depth, row["class_id"])]:
                    nodes = abstract_nodes.get((rep["id"], depth))
                    out.append(f"**rank{rep['rank']} / {rep['strategy']} / pair id = {rep['id']}**")
                    out.append("")
                    if not nodes:
                        out.append("(cutout が見つかりません)")
                        out.append("")
                        continue
                    out.append(f"value: `{rep['value'].strip()}`")
                    out.append("")
                    out.append("```")
                    out.extend(render_cut(nodes))
                    out.append("```")
                    out.append("")

            md_path = out_dir / f"{source}_gp" / f"large_clusters_{sigma_disp}.md"
            md_path.write_text("\n".join(out) + "\n", encoding="utf-8")
            print("wrote", md_path, flush=True)
