"""E5: fast 側 (head) の多様性分析.

E1 ベスト設定 (τ=0.7, L0, Diff) の 7 既知パターン top class について、
そのメンバの **fast 側 AST 断片** (outputs/AST_HEAD/scope_DIFF_BLOCK_all.json の
merged.nodes) を取得し、 bigram Jaccard で variant クラスタリングして
何種類の高速化方法が存在するかを集計する。

paper §6.2「ペアとなっている fast 側の類似性」 への主データ。

出力:
    outputs/scam/approach_minimum/analysis/E5_fast_variants.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (
    KNOWN_PATTERNS,
    ensure_out_dir,
    load_ast_head,
    load_classes,
    load_rq1_ground_truth,
    normalize_value,
)

# E1 ベスト設定 (τ=0.7 / L0 / Diff) のパラメータ
BEST_TAU = 0.7
BEST_LEVEL = 0
BEST_DEPTH = "Diff"

# fast 側クラスタリングの閾値 (緩い閾値で variant をある程度集約)
FAST_TAU = 0.5


def head_bigrams(record: dict) -> frozenset:
    """AST_HEAD record の merged.nodes から bigram set を作る。

    slow 側と同じトークン化規約: ``(name, normalize_value(value))``。
    head 側に variadic フラグは無いため、 そのまま全ノードを使う。
    """
    nodes = record.get("merged", {}).get("nodes", [])
    tokens = [(n["name"], normalize_value(n.get("value"))) for n in nodes]
    if len(tokens) < 2:
        return frozenset()
    return frozenset(tuple(tokens[i : i + 2]) for i in range(len(tokens) - 1))


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def variant_clustering(items: list[tuple[int, frozenset]], tau: float) -> list[list[int]]:
    """簡易 greedy クラスタリング.

    items: ``[(mb_id, bigram_set), ...]``
    各 mb_id を既存 variant のいずれかと Jaccard ≥ tau なら統合、 さもなくば新 variant。
    """
    variants: list[tuple[frozenset, list[int]]] = []  # [(union_bigrams, [mb_ids])]
    for mb_id, bg in items:
        merged_into = None
        for i, (vbg, ids) in enumerate(variants):
            if jaccard(bg, vbg) >= tau:
                merged_into = i
                break
        if merged_into is None:
            variants.append((bg, [mb_id]))
        else:
            vbg, ids = variants[merged_into]
            variants[merged_into] = (vbg | bg, ids + [mb_id])
    return [ids for _, ids in variants]


def get_pattern_top1_members() -> dict[int, tuple[str, list[int]]]:
    """E1 ベスト設定の 7 既知パターン top1 クラスとそのメンバを返す。

    Returns:
        ``{pattern_id: (top1_class_id, [mb_id, ...])}``
    """
    classes = load_classes(BEST_TAU, BEST_LEVEL, BEST_DEPTH)
    out: dict[int, tuple[str, list[int]]] = {}
    for pid in KNOWN_PATTERNS:
        gt = load_rq1_ground_truth(pid)
        gp = {int(r["mb_id"]) for r in gt}

        from collections import Counter

        counter: Counter = Counter()
        for cid, members in classes.items():
            mb_ids = [int(m.split("_")[0]) for m in members]
            n_known = sum(1 for m in mb_ids if m in gp)
            if n_known > 0:
                counter[cid] = n_known
        if counter:
            top_cid, _ = counter.most_common(1)[0]
            top_mb_ids = sorted([int(m.split("_")[0]) for m in classes[top_cid]])
            out[pid] = (top_cid, top_mb_ids)
    return out


def main() -> None:
    out_dir = ensure_out_dir()
    print(f"[INFO] AST_HEAD scope_DIFF_BLOCK_all.json をロード中 ...", flush=True)
    ast_head = load_ast_head(BEST_DEPTH)
    print(f"[INFO] loaded: {len(ast_head)} records", flush=True)

    pattern_tops = get_pattern_top1_members()
    print(f"[INFO] 7 パターン top1 クラスを取得", flush=True)

    rows: list[dict] = []
    for pid, (cid, mb_ids) in sorted(pattern_tops.items()):
        # 各メンバの head 側 bigram を作る
        items: list[tuple[int, frozenset]] = []
        for mb_id in mb_ids:
            rec = ast_head.get(mb_id)
            if rec is None:
                continue
            bg = head_bigrams(rec)
            items.append((mb_id, bg))
        # variant クラスタリング
        variants = variant_clustering(items, FAST_TAU)
        # 大きい順にソート
        variants.sort(key=lambda v: -len(v))
        print(f"\n=== pattern {pid} (top1={cid}, size={len(mb_ids)}) ===")
        print(f"  fast 側 variant 数: {len(variants)}")
        for vi, ids in enumerate(variants[:5]):
            head_sample = ast_head[ids[0]]["merged"]["nodes"][:6]
            head_tokens = " ".join(f"{n['name']}:{normalize_value(n.get('value'))}" for n in head_sample)
            print(f"    variant #{vi + 1} (size={len(ids)}): rep_mb_id={ids[0]} → head: {head_tokens[:80]}...")
            rows.append(
                {
                    "pattern_id": pid,
                    "top1_class_id": cid,
                    "top1_class_size": len(mb_ids),
                    "variant_id": vi + 1,
                    "variant_size": len(ids),
                    "representative_mb_id": ids[0],
                    "representative_head_tokens": head_tokens[:200],
                    "member_mb_ids": ",".join(str(m) for m in ids[:20]),
                }
            )
        # 残り variant も CSV に書く (skipped from stdout)
        for vi, ids in enumerate(variants[5:], start=6):
            head_sample = ast_head[ids[0]]["merged"]["nodes"][:6]
            head_tokens = " ".join(f"{n['name']}:{normalize_value(n.get('value'))}" for n in head_sample)
            rows.append(
                {
                    "pattern_id": pid,
                    "top1_class_id": cid,
                    "top1_class_size": len(mb_ids),
                    "variant_id": vi,
                    "variant_size": len(ids),
                    "representative_mb_id": ids[0],
                    "representative_head_tokens": head_tokens[:200],
                    "member_mb_ids": ",".join(str(m) for m in ids[:20]),
                }
            )

    csv_path = out_dir / "E5_fast_variants.csv"
    fields = ["pattern_id", "top1_class_id", "top1_class_size", "variant_id", "variant_size", "representative_mb_id", "representative_head_tokens", "member_mb_ids"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n[OUTPUT] {csv_path}")


if __name__ == "__main__":
    main()
