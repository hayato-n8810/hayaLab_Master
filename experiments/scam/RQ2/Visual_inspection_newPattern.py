"""新パターン候補クラスタの目視調査用 CSV を生成する。

概要:
    outputs/scam/approach_minimum/integrate_complete/jaccard07/level{0,1}/{Diff,Brother}
    の 4 ディレクトリのクラスタから、既知 7 パターン (PreAnalysis/matches.jsonl の mb_id) を
    含まないクラスタを抽出し、size 降順上位 TOP_K 件を新規パターン候補とする。

    各クラスタについて、代表メンバー 1 件を必ず含む bigram Jaccard 類似度上位 SAMPLE_N 件を
    選定し、MBDiff.json から base/head コード対を取り出して CSV 化する。

    出力先:
        outputs/scam/RQ2/jaccard07/
        ├── level0/Diff/{summary.csv, README.md, rank01_*.csv ... rank10_*.csv}
        ├── level0/Brother/...
        ├── level1/Diff/...
        └── level1/Brother/...

実行:
    uv run python experiments/scam/RQ2/Visual_inspection_newPattern.py
"""

from __future__ import annotations

import csv
import json
import shutil
from difflib import unified_diff
from pathlib import Path
from typing import Any

import ijson

from hayalab.config import PathConfig


def extract_added_removed(base_code: str, head_code: str) -> tuple[str, str]:
    """unified_diff で base→head 間の削除行(-)と追加行(+)を分離する。

    Args:
        base_code: slow 側コード。
        head_code: fast 側コード。

    Returns:
        (removed_lines, added_lines) の改行連結文字列 2 値。
    """
    diff = unified_diff(
        base_code.splitlines(),
        head_code.splitlines(),
        fromfile="base",
        tofile="head",
        lineterm="",
    )
    removed: list[str] = []
    added: list[str] = []
    for line in diff:
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            removed.append(line)
        elif line.startswith("+"):
            added.append(line)
    return "\n".join(removed), "\n".join(added)


CONFIG = PathConfig()

INTEGRATE_ROOT = CONFIG.outputs / "scam/approach_minimum/integrate_complete/jaccard07"
MBDIFF_JSON = CONFIG.processed / "MBDiff.json"
OUTPUT_ROOT = CONFIG.outputs / "scam/RQ2/visual_inspection"

LEVEL_DEPTHS: list[tuple[str, str]] = [
    ("level0", "Diff"),
    ("level0", "Brother"),
    ("level1", "Diff"),
    ("level1", "Brother"),
]

TOP_K = 30
SAMPLE_N = 5


# ---------------------------------------------------------------------------
# Bigram Jaccard helpers
# ---------------------------------------------------------------------------


def compute_bigrams(value: str) -> frozenset[tuple[str, str]]:
    """トークン列文字列から bigram 集合を返す。

    Args:
        value: スペース区切りのトークン列。

    Returns:
        連続する 2 トークンのペアの frozenset。
    """
    tokens = value.split()
    return frozenset(zip(tokens, tokens[1:])) if len(tokens) >= 2 else frozenset()


def jaccard(a: frozenset[tuple[str, str]], b: frozenset[tuple[str, str]]) -> float:
    """bigram 集合間の Jaccard 類似度を返す。

    Args:
        a: bigram 集合 A。
        b: bigram 集合 B。

    Returns:
        |A ∩ B| / |A ∪ B|。両方空なら 1.0。
    """
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_known_mb_ids() -> set[int]:
    """PreAnalysis/<pattern_number>/diff_linked.jsonl から既知 7 パターン該当 mb_id 集合を構築する。

    Returns:
        既知パターンに該当する mb_id の集合。
    """
    ids: set[int] = set()
    for i in range(1, 11):
        jsonl_path = CONFIG.outputs / f"scam/PreAnalysis/pattern_{i}/diff_linked.jsonl"
        print(f"  loading known mb_ids from {jsonl_path}")
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                mb_id = obj.get("mb_id")
                if isinstance(mb_id, int):
                    ids.add(mb_id)
    return ids


def load_cluster_data(level: str, depth: str) -> tuple[dict[str, list[int]], dict[str, dict[str, Any]]]:
    """クラスタのメンバーと mode_medoid 情報を読み込む。

    Args:
        level: "level0" または "level1"。
        depth: "Diff" または "Brother"。

    Returns:
        (members_by_cluster, medoid_by_cluster)
            - members_by_cluster: cluster_id → [mb_id, ...]（int 化済み）
            - medoid_by_cluster: cluster_id → {size, representative, ...}
    """
    base_dir = INTEGRATE_ROOT / level / depth
    classes_path = base_dir / f"{depth}.json"
    medoid_path = base_dir / f"{depth}_pattern_mode_medoid.json"

    with open(classes_path, encoding="utf-8") as f:
        classes_obj = json.load(f)
    with open(medoid_path, encoding="utf-8") as f:
        medoid_obj = json.load(f)

    members_by_cluster: dict[str, list[int]] = {}
    for cluster_id, member_strs in classes_obj["classes"].items():
        ids = []
        for s in member_strs:
            mb_str = s.split("_", 1)[0]
            try:
                ids.append(int(mb_str))
            except ValueError:
                continue
        members_by_cluster[cluster_id] = ids

    medoid_by_cluster: dict[str, dict[str, Any]] = dict(medoid_obj["classes"])
    return members_by_cluster, medoid_by_cluster


def load_cluster_labels_for_ids(
    level: str,
    depth: str,
    cluster_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """必要な cluster_id 分だけ label データを返す。

    Args:
        level: "level0" または "level1"。
        depth: "Diff" または "Brother"。
        cluster_ids: 取得対象の cluster_id 集合。

    Returns:
        {cluster_id: [{id: mb_id, value: str}, ...]}。
    """
    label_path = INTEGRATE_ROOT / level / depth / f"{depth}_label.json"
    with open(label_path, encoding="utf-8") as f:
        all_labels: dict[str, list[dict[str, Any]]] = json.load(f)
    return {cid: all_labels[cid] for cid in cluster_ids if cid in all_labels}


# ---------------------------------------------------------------------------
# Cluster selection
# ---------------------------------------------------------------------------


def select_top_clusters(
    members_by_cluster: dict[str, list[int]],
    medoid_by_cluster: dict[str, dict[str, Any]],
    known_mb_ids: set[int],
    top_k: int,
) -> list[tuple[str, int, list[int], dict[str, Any]]]:
    """既知パターンを含まないクラスタを size 降順 top_k で返す。

    Args:
        members_by_cluster: cluster_id → members。
        medoid_by_cluster: cluster_id → medoid info。
        known_mb_ids: 除外対象の mb_id 集合。
        top_k: 返す件数。

    Returns:
        [(cluster_id, size, members, medoid_info), ...] を size 降順、
        同 size は cluster_id 昇順で安定ソートして上位 top_k 件返す。
    """
    candidates: list[tuple[str, int, list[int], dict[str, Any]]] = []
    for cluster_id, members in members_by_cluster.items():
        if cluster_id not in medoid_by_cluster:
            continue
        if any(m in known_mb_ids for m in members):
            continue
        size = int(medoid_by_cluster[cluster_id].get("size", len(members)))
        candidates.append((cluster_id, size, members, medoid_by_cluster[cluster_id]))

    candidates.sort(key=lambda x: (-x[1], x[0]))
    return candidates[:top_k]


def resolve_representative_id(medoid_info: dict[str, Any], members: list[int]) -> int:
    """Medoid 情報から代表 mb_id を返す。無ければメンバー先頭を代表とする。

    Args:
        medoid_info: medoid ファイルのクラスタエントリ。
        members: クラスタメンバー。

    Returns:
        代表 mb_id。
    """
    rep = medoid_info.get("representative")
    if isinstance(rep, dict):
        rid = rep.get("id")
        if isinstance(rid, int):
            return rid
    return members[0] if members else -1


def select_top_similar(
    labels: list[dict[str, Any]],
    representative_id: int,
    rep_value: str,
    n: int,
) -> list[tuple[int, bool, float]]:
    """代表値との bigram Jaccard 類似度上位 n 件を返す（代表は必ず含む）。

    Args:
        labels: [{id: mb_id, value: str}, ...]（クラスタメンバー全件）。
        representative_id: 代表メンバーの mb_id。
        rep_value: 代表メンバーのトークン列文字列。
        n: 取得件数。クラスタ size < n の場合は全件返す。

    Returns:
        [(mb_id, is_representative, similarity_to_rep), ...] を
        similarity 降順（同スコアは代表優先、次に mb_id 昇順）で返す。
    """
    rep_bigrams = compute_bigrams(rep_value)
    scored: list[tuple[int, bool, float]] = []
    for item in labels:
        mb_id = item["id"]
        value = item.get("value", "")
        sim = jaccard(rep_bigrams, compute_bigrams(value))
        scored.append((mb_id, mb_id == representative_id, sim))

    # 類似度降順、同スコアは代表優先、次に mb_id 昇順
    scored.sort(key=lambda x: (-x[2], not x[1], x[0]))
    selected = scored[:n]

    # 代表が top-n に入らなかった edge case（size > n かつ代表が低類似度）：末尾と交換
    if selected and not any(is_r for _, is_r, _ in selected):
        rep_entries = [(mid, ir, s) for mid, ir, s in scored if ir]
        if rep_entries:
            selected[-1] = rep_entries[0]

    return selected


# ---------------------------------------------------------------------------
# MBDiff streaming
# ---------------------------------------------------------------------------


def stream_mbdiff_codes(mbdiff_path: Path, needed_ids: set[int]) -> dict[int, tuple[str, str]]:
    """MBDiff.json をストリーミング読みして必要 id の base/head コードを取得する。

    Args:
        mbdiff_path: MBDiff.json のパス。
        needed_ids: 取得対象の mb_id 集合。

    Returns:
        {mb_id: (base_code, head_code)}。見つからなかった id は含まれない。
    """
    code_map: dict[int, tuple[str, str]] = {}
    remaining = set(needed_ids)
    with open(mbdiff_path, "rb") as f:
        for record in ijson.items(f, "item"):
            rid = record.get("id")
            if not isinstance(rid, int) or rid not in remaining:
                continue
            diff = record.get("diff", {}) or {}
            base_ast = diff.get("base_ast", {}) or {}
            head_ast = diff.get("head_ast", {}) or {}
            base_code = base_ast.get("code", "") or ""
            head_code = head_ast.get("code", "") or ""
            code_map[rid] = (base_code, head_code)
            remaining.discard(rid)
            if not remaining:
                break
    return code_map


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_cluster_md(
    out_path: Path,
    cluster_id: str,
    rank: int,
    cluster_size: int,
    representative_value: str,
    sampled: list[tuple[int, bool, float]],
    code_map: dict[int, tuple[str, str]],
) -> int:
    """1 クラスタ分の目視調査 Markdown を書き出す。

    ファイルは 2 セクション構成：
      1. 代表値と仮説記入欄（読んで → 仮説を書く）
      2. サンプルコードと判定欄（1件ずつ確認 → pattern_match を書く）

    Args:
        out_path: 出力先 .md パス。
        cluster_id: クラスタ ID。
        rank: size 順位 (1..top_k)。
        cluster_size: クラスタの母集団サイズ。
        representative_value: 代表値トークン列。
        sampled: [(mb_id, is_representative, similarity_to_rep), ...]。
        code_map: mb_id → (base_code, head_code)。

    Returns:
        実際に書き出したサンプル数。
    """
    lines: list[str] = []

    # ── セクション 1: 代表値と仮説記入欄 ──────────────────────────────
    lines += [
        f"# Rank {rank:02d} — `{cluster_id}` (size: {cluster_size})",
        "",
        "## 判定方法",
        "",
        "- **代表値が JS 性能上の意味を持つ実装パターンを表しているか (Yes/No)**: ",
        "- **5 件の実装対を参照し，4つ以上の変換意図が一貫しているか (Yes/No)**: ",
        "- **採用/棄却**:上記の二つが共に Yes なら採用、そうでなければ棄却",
        "",
        "### 採用の場合意味づけ",
        "- **Slow側の処理内容**: ",
        "- **Fast側への変換意図**: ",
        "",
        "---",
        "",
        "## 例",
        "",
        "```js",
        "// slow",
        "VAR_A = String(VAR_A);",
        "// fast",
        "VAR_A = '' + VAR_A;",
        "```",
        "- **代表値が JS 性能上の意味を持つ実装パターンを表しているか (Yes/No)**: Yes",
        "- **5 件の実装対を参照し，その過半数（３つ以上）の変換意図が一貫しているか (Yes/No)**: Yes",
        "",
        "### 採用の場合意味づけ",
        "- **Slow側の処理内容**: String() を使った文字列化",
        "- **Fast側への変換意図**: 文字列の連結による文字列化",
        "",
        "---",
        "",
        "## クラスタの代表値",
        "",
        "```",
        representative_value,
        "```",
        "",
        "- 設定:",
        " $v：変数，$s：文字列リテラル，$n：数値リテラル，$r：正規表現リテラル",
    ]

    # ── セクション 2: サンプルコードと判定欄 ──────────────────────────
    lines += [
        f"## サンプル（代表値との類似度上位 {SAMPLE_N} 件）",
        "",
    ]

    written = 0
    total = len(sampled)
    for i, (mb_id, is_rep, sim) in enumerate(sampled, start=1):
        if mb_id not in code_map:
            continue
        written += 1
        base_code, head_code = code_map[mb_id]
        removed, added = extract_added_removed(base_code, head_code)

        rep_mark = "★代表  " if is_rep else ""
        lines += [
            f"### [{i}/{total}] mb\\_id={mb_id}  {rep_mark}sim={sim:.4f}",
            "",
            "**slow 側（base_code）**",
            "",
            "```js",
            base_code.rstrip(),
            "```",
            "",
            "**fast 側（head_code）**",
            "",
            "```js",
            head_code.rstrip(),
            "```",
            "",
        ]
        if removed or added:
            lines += [
                "**変更箇所**",
                "",
                "```diff",
                *(removed.splitlines() if removed else []),
                *(added.splitlines() if added else []),
                "```",
                "",
            ]
        lines += [
            "- **memo**: ",
            "",
        ]
        if i < total:
            lines += ["---", ""]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return written


def write_judgment_csv(out_path: Path, records: list[dict[str, Any]]) -> None:
    """設定単位の判定 CSV を書き出す（横軸=判定項目、縦軸=クラスタ）。

    各行が 1 クラスタに対応する。

    自動入力列（参照用）: rank, cluster_id, cluster_size, 代表値, md_file
    記入列（ユーザーが埋める）: 採用/棄却, Slow側の処理内容, Fast側への変換意図

    Args:
        out_path: 出力先 .csv パス。
        records: process_one_direction が返す cluster record のリスト。
                 各要素に "md_filename" キーが追加済みであること。
    """
    fieldnames = [
        "rank",
        "cluster_id",
        "cluster_size",
        "代表値",
        "md_file",
        "採用/棄却",
        "（採用の場合）Slow側の処理内容",
        "（採用の場合）Fast側への変換意図",
    ]
    rows = [
        {
            "rank": f"rank{rec['rank']:02d}",
            "cluster_id": rec["cluster_id"],
            "cluster_size": rec["size"],
            "代表値": rec["representative_value"],
            "md_file": rec["md_filename"],
            "採用/棄却": "",
            "（採用の場合）Slow側の処理内容": "",
            "（採用の場合）Fast側への変換意図": "",
        }
        for rec in records
    ]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def write_method_md(out_path: Path) -> None:
    """出力ルート直下に METHOD.md を書き出す（全設定共通）。"""
    content = f"""\
# 新パターン候補 目視調査 — 方法

## 対象/抽出条件

- サイズ戦略2（差分のみ・差分とその兄弟）* 抽象度2 = 計4設定
- 事前分析で判定した従来研究のパターンを示すslowコードを 1 件でも含むクラスタは除外
- 残ったクラスタを所属している要素数の降順で並べ、上位 {TOP_K} 件が新規パターン候補


## サンプリング

- 各クラスタにつき **代表メンバー 1 件を必ず含む （集約時に用いたJaccard）類似度上位 {SAMPLE_N} 件** を選定
- クラスタ size < {SAMPLE_N} の場合は全件出力

## ファイル構成（設定ごとのサブディレクトリ）

| ファイル | 役割 |
|---|---|
| `answer_book.csv` | **判定記入用**（1行=1クラスタ） |
| `rank{{NN}}_*.md` | **コード閲覧用**（代表値 + slow/fast コード） |

## answer_book.csv の列

| 列 | 内容 |
|---|---|
| rank | サイズ順位 |
| cluster_id | クラスタ ID |
| cluster_size | クラスタサイズ |
| 代表値 | 代表トークン列（仮説の起点） |
| md_file | 対応するコード閲覧ファイル |
| 採用/棄却 | 【記入】採用 / 要検討 / 棄却 |
| Slow側の処理内容 | 【記入】slow 側コードが何をしているか |
| Fast側への変換意図 | 【記入】fast 側での書き換え内容 |

## 目視フロー

1. `answer_book.csv` から各行の **md_file** 列のファイル名を開いてコードを確認する
2. 採用基準: {SAMPLE_N} 件のサンプルを確認し、判定項目2つを満たしているかを判定
3. `answer_book.csv` に戻り **採用/棄却**・**Slow側の処理内容**・**Fast側への変換意図** を記入する

## 判定項目

判定1：代表値が実装内容を表現しているか YES/NO
判定2：サンプル {SAMPLE_N} 件中 {SAMPLE_N - 1} 件以上 の変換意図が一致するか YES/NO
"""
    out_path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def process_one_direction(
    level: str,
    depth: str,
    known_mb_ids: set[int],
) -> tuple[list[dict[str, Any]], set[int]]:
    """1 つの (level, depth) ディレクトリの top クラスタを抽出する。

    Args:
        level: "level0" or "level1"。
        depth: "Diff" or "Brother"。
        known_mb_ids: 既知パターン mb_id 集合。

    Returns:
        (cluster_records, needed_ids)
            - cluster_records: 各クラスタの dict（書き出し用情報を保持）
            - needed_ids: base/head コードが必要な mb_id 集合
    """
    members_by_cluster, medoid_by_cluster = load_cluster_data(level, depth)
    selected = select_top_clusters(members_by_cluster, medoid_by_cluster, known_mb_ids, TOP_K)

    cluster_ids = {cluster_id for cluster_id, _, _, _ in selected}
    labels_by_cluster = load_cluster_labels_for_ids(level, depth, cluster_ids)

    records: list[dict[str, Any]] = []
    needed_ids: set[int] = set()
    for rank, (cluster_id, size, members, medoid_info) in enumerate(selected, start=1):
        representative_id = resolve_representative_id(medoid_info, members)
        rep_info = medoid_info.get("representative")
        rep_value = (rep_info.get("value", "") if isinstance(rep_info, dict) else "") or ""

        labels = labels_by_cluster.get(cluster_id, [])
        sampled = select_top_similar(labels, representative_id, rep_value, SAMPLE_N)

        for mb_id, _, _ in sampled:
            needed_ids.add(mb_id)
        records.append(
            {
                "rank": rank,
                "cluster_id": cluster_id,
                "size": size,
                "representative_id": representative_id,
                "representative_value": rep_value,
                "sampled_n": len(sampled),
                "members": members,
                "sampled": sampled,
            }
        )
    return records, needed_ids


def output_direction(
    level: str,
    depth: str,
    records: list[dict[str, Any]],
    code_map: dict[int, tuple[str, str]],
) -> None:
    """1 つの (level, depth) について全成果物を書き出す。"""
    out_dir = OUTPUT_ROOT / level / depth
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    enriched: list[dict[str, Any]] = []
    for rec in records:
        rank = rec["rank"]
        cluster_id = rec["cluster_id"]
        md_filename = f"rank{rank:02d}_{cluster_id}.md"
        write_cluster_md(
            out_path=out_dir / md_filename,
            cluster_id=cluster_id,
            rank=rank,
            cluster_size=rec["size"],
            representative_value=rec["representative_value"],
            sampled=rec["sampled"],
            code_map=code_map,
        )
        enriched.append({**rec, "md_filename": md_filename})

    write_judgment_csv(out_dir / "answer_book.csv", enriched)
    print(f"  wrote {len(records)} clusters → {out_dir}")


def main() -> None:
    """エントリポイント。4 ディレクトリ分の top クラスタ抽出と CSV 出力を行う。"""
    known_mb_ids = load_known_mb_ids()

    print("[2/4] selecting top clusters per direction")
    direction_records: list[tuple[str, str, list[dict[str, Any]]]] = []
    needed_ids: set[int] = set()
    for level, depth in LEVEL_DEPTHS:
        print(f"  - {level}/{depth}")
        records, ids = process_one_direction(level, depth, known_mb_ids)
        direction_records.append((level, depth, records))
        needed_ids |= ids
    print(f"    needed mb_ids: {len(needed_ids)}")

    print(f"[3/4] streaming MBDiff.json to fetch {len(needed_ids)} pairs")
    code_map = stream_mbdiff_codes(MBDIFF_JSON, needed_ids)
    missing = needed_ids - set(code_map)
    print(f"    fetched: {len(code_map)}  missing: {len(missing)}")
    if missing:
        print(f"    missing sample: {sorted(missing)[:10]}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_method_md(OUTPUT_ROOT / "METHOD.md")

    print(f"[4/4] writing outputs under {OUTPUT_ROOT}")
    for level, depth, records in direction_records:
        output_direction(level, depth, records, code_map)

    print("done")


if __name__ == "__main__":
    main()
