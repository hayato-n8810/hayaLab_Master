r"""クラスタメンバ間で元の AST が共通するノードのみを集め、終端ノードの value を連結する。

抽象化前の具象 AST（``cutouts.json`` の cut）を土台に、クラスタ全メンバーの共通部分木を
``anti_unify`` で求める。値まで一致したノード（``kind == "concrete"``）だけを残し、
そのうち label が ``"name: value [begin,end]"`` 形式の終端ノードを出現順に取り出して
1 本の文字列に連結する（``print_tree.py`` と同じ形式）。

抽象化を通さないため、共通部分は識別子・リテラルまで literal に一致したノードに限られる。
punctuation は具象 cut に残っているので連結結果はコードとして読める。

対象は τ0.7 / α0 の σ1 (Diff) / σ2 (Brother) / σ3 (ExParent)。各 depth の規模上位
TOP_N クラスタについて出力する。

正解集合との対応を注記するため、結果は ``old_gp/`` と ``new_gp/`` に分けて出力する。
規模のランキング自体は正解集合に依存しない。

入力:
    outputs/scam/PreAnalysis/matches.jsonl                  old G_p（注記用）
    outputs/saner/PreAnalysis/base_only_hits.jsonl          new G_p（注記用）
    outputs/scam/approach/integrate/.../{depth}_label.json  クラスタとメンバー
    outputs/scam/approach/cutouts.json                      具象 cut（punctuation を含む）

出力:
    outputs/saner/{old,new}_gp/common_nodes.jsonl        クラスタごとの連結文字列
    outputs/saner/{old,new}_gp/common_nodes_{sigma}.md   目視用（連結文字列 + 共通部分木）
"""

from __future__ import annotations

import json
import re

import ijson

from hayalab.config import PathConfig
from hayalab.scam.generalize import anti_unify

# --- 対象設定 ---------------------------------------------------------------
TAU_DIR: str = "jaccard07"
TAU_DISP: str = "0.7"
LEVEL: int = 1
ALPHA_DISP: str = "a0"
DEPTHS: list[tuple[str, str]] = [("Diff", "s1"), ("Brother", "s2"), ("ExParent", "s3")]
GP_SOURCES: list[str] = ["old", "new"]

# --- 出力の制御 -------------------------------------------------------------
# 対象とするクラスタ規模の下限
MIN_SIZE: int = 3
# 規模降順で処理するクラスタ数
TOP_N: int = 30
# 共通部分木の計算に使うメンバー数の上限（pair id 昇順で切る）
MAX_MEMBERS: int = 20
# 木 1 本あたりの最大表示ノード数
MAX_NODES: int = 60
# value を連結するときの区切り文字（print_tree.py と同じ）
VALUE_SEPARATOR: str = " "

# 終端ノード判定: ``"name: value [...]"`` 形式の label にマッチ
TERMINAL_LABEL_RE = re.compile(r"([^ ]+): (.+)")


# --- ヘルパ（設定ごとに呼ばれる） -------------------------------------------
def load_setting(integrate_dir, depth: str) -> dict[str, list[int]]:
    """1 設定の ``class_id -> メンバー pair id リスト`` を返す。

    Args:
        integrate_dir: integrate 出力のルートディレクトリ。
        depth: 対象 depth。

    Returns:
        ``{class_id: [pair id, ...]}``。
    """
    label_path = integrate_dir / TAU_DIR / f"level{LEVEL}" / depth / f"{depth}_label.json"
    if not label_path.exists():
        raise FileNotFoundError(f"label not found: {label_path}")
    with label_path.open(encoding="utf-8") as f:
        classes = json.load(f)
    return {cid: [int(r["id"]) for r in rows] for cid, rows in classes.items()}


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
def common_terminal_text(generalized: list[dict]) -> str:
    """共通部分木のうち、値まで一致した終端ノードの value を出現順に連結する。

    Args:
        generalized: ``anti_unify`` の返り値。

    Returns:
        連結したテキスト。該当ノードが無ければ空文字列。
    """
    return VALUE_SEPARATOR.join(node["value"] for node in generalized if node["kind"] == "concrete" and node["value"] and TERMINAL_LABEL_RE.match(node.get("label", "")))


def render_generalized(generalized: list[dict]) -> list[str]:
    """共通部分木をインデント付きの木として描画する。

    Args:
        generalized: ``anti_unify`` の返り値。

    Returns:
        描画行のリスト。行頭 ``~`` は value 相違、``?`` は name 相違、``+`` は子の個数相違。
    """
    marker = {"concrete": " ", "value_hole": "~", "node_hole": "?", "tail_hole": "+"}
    lines = [f"{marker[g['kind']]} {'  ' * g['depth']}{g['name']}{('  ' + g['value']) if g['value'] else ''}" for g in generalized[:MAX_NODES]]
    if len(generalized) > MAX_NODES:
        lines.append(f"  ... 他 {len(generalized) - MAX_NODES} ノード")
    return lines


# --- メインフロー -----------------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: パス解決 ---
    path_config = PathConfig()
    matches_path = path_config.outputs / "scam" / "PreAnalysis" / "matches.jsonl"
    base_only_path = path_config.outputs / "saner" / "PreAnalysis" / "base_only_hits.jsonl"
    integrate_dir = path_config.outputs / "scam" / "approach" / "integrate"
    cutouts_path = path_config.outputs / "scam" / "approach" / "cutouts.json"
    out_dir = path_config.outputs / "saner"
    out_dir.mkdir(parents=True, exist_ok=True)
    for required in (matches_path, base_only_path, integrate_dir, cutouts_path):
        if not required.exists():
            raise FileNotFoundError(f"input not found: {required}")
    print(f"[SETTING] τ{TAU_DISP} / {ALPHA_DISP} / level{LEVEL}, depths={[d for d, _ in DEPTHS]}", flush=True)

    # --- Section 2: 正解集合（2 種） ---
    gp_all = load_gp(matches_path, base_only_path)
    patterns = sorted({p for table in gp_all.values() for p, ids in table.items() if ids})
    print("評価対象パターン:", patterns, flush=True)

    # --- Section 3: depth ごとに規模上位クラスタを選び、必要な pair を集める ---
    targets: dict[str, list[dict]] = {}
    needed: dict[str, set[int]] = {}
    for depth, sigma_disp in DEPTHS:
        members_of = load_setting(integrate_dir, depth)
        rows = []
        for class_id, ids in members_of.items():
            if len(ids) < MIN_SIZE:
                continue
            row = {
                "sigma": sigma_disp,
                "depth": depth,
                "class_id": class_id,
                "size": len(ids),
                "members": sorted(ids)[:MAX_MEMBERS],
            }
            for source in GP_SOURCES:
                hit_patterns = [p for p in patterns if gp_all[source].get(p, set()).intersection(ids)]
                row[f"{source}_gp_patterns"] = " ".join(str(p) for p in hit_patterns)
                row[f"{source}_gp_tp"] = sum(len(gp_all[source].get(p, set()).intersection(ids)) for p in hit_patterns)
            rows.append(row)
        rows.sort(key=lambda r: (-r["size"], r["class_id"]))
        targets[depth] = rows[:TOP_N]
        needed.setdefault(depth, set()).update(m for r in targets[depth] for m in r["members"])
        print(f"[{sigma_disp}] 上位 {len(targets[depth])} クラスタ / 必要 pair {len(needed[depth])} 件", flush=True)

    # --- Section 4: 具象 cut を 1 パスで収集 ---
    all_ids = set().union(*needed.values())
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

    # --- Section 5: 共通ノードを抽出して連結・正解集合ごとに出力 ---
    records: list[dict] = []
    for source in GP_SOURCES:
        for depth, sigma_disp in DEPTHS:
            out: list[str] = []
            out.append(f"# クラスタメンバの共通ノード（{source} G_p / 元の AST・τ{TAU_DISP} / {ALPHA_DISP} / {sigma_disp} = {depth}）")
            out.append("")
            out.append(f"規模降順の上位 {TOP_N} クラスタについて、最大 {MAX_MEMBERS} メンバーの共通部分木を求め、")
            out.append("値まで一致した終端ノード（label が `name: value [begin,end]` 形式）の value を出現順に連結した。")
            out.append("抽象化を通さないため、識別子・リテラルまで literal に一致したノードのみが残る。")
            out.append("")
            out.append("木の行頭は `~` value 相違 / `?` name 相違 / `+` 子の個数相違。")
            out.append("")

            for rank, row in enumerate(targets[depth], start=1):
                cuts = [concrete[(m, depth)] for m in row["members"] if (m, depth) in concrete]
                generalized = anti_unify(cuts) if cuts else []
                text = common_terminal_text(generalized)
                n_concrete = sum(1 for g in generalized if g["kind"] == "concrete")
                records.append(
                    {
                        "gp_source": source,
                        "sigma": sigma_disp,
                        "class_id": row["class_id"],
                        "size": row["size"],
                        "n_members_used": len(cuts),
                        "n_common_nodes": n_concrete,
                        "gp_patterns": row[f"{source}_gp_patterns"],
                        "gp_tp": row[f"{source}_gp_tp"],
                        "text": text,
                    }
                )
                hits = row[f"{source}_gp_patterns"]
                gp_label = f"P{hits.replace(' ', ' P')} (TP={row[f'{source}_gp_tp']})" if hits else "新規候補"
                out.append(f"## #{rank} `{row['class_id']}` — size={row['size']}, 共通ノード {n_concrete}, 使用 {len(cuts)} 件 — {gp_label}")
                out.append("")
                out.append(f"text: `{text}`" if text else "text: (共通する終端ノードなし)")
                out.append("")
                if generalized:
                    out.append("```")
                    out.extend(render_generalized(generalized))
                    out.append("```")
                    out.append("")

            source_dir = out_dir / f"{source}_gp"
            source_dir.mkdir(parents=True, exist_ok=True)
            md_path = source_dir / f"common_nodes_{sigma_disp}.md"
            md_path.write_text("\n".join(out) + "\n", encoding="utf-8")
            print("wrote", md_path, flush=True)

    for source in GP_SOURCES:
        subset = [r for r in records if r["gp_source"] == source]
        jsonl_path = out_dir / f"{source}_gp" / "common_nodes.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as f:
            for record in subset:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"wrote {jsonl_path} ({len(subset)} 行)", flush=True)
