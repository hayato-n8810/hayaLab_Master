"""Phase 3: phase2 の代表を ``find_tree_matches`` が受け付けるパターン仕様 JSON に書き出す。

phase2 の代表は ``patterns`` にノード仕様を直接並べた JSONL であり、``load_tree_patterns`` が
要求する ``{"version", "ignore_names", "patterns": [{"id", "key", "root"}]}`` の形ではない。
``pattern_id`` にクラスタ ID、``root`` にノード仕様を当てはめて変換する。``ignore_names`` は
phase2 のサマリに記録された値を全パターン共通で用いる。

切り出しは森であり、代表は成分ごとにノード仕様を持つ。phase2 はこれを仮想ルートで束ねているが、
仮想ルートは AST に対応するノードを持たないため照合できない。ここで ``{"name": "*"}`` を根として
補い、各成分を ``match: "descendant"`` の子として並べることで 1 クラスタ 1 パターンにする。
成分が 1 つのクラスタは根を補わず、その成分をそのまま ``root`` にする。

``{"name": "*"}`` は任意のノードに一致するため、成分をすべて部分木に含むノードのいずれもが
起点になりうる。1 レコードに対して祖先の数だけ重複してヒットする点に注意する。

代表が空のクラスタ（共通部分木が取れなかったもの）はパターンを持たないため除外する。

出力:
    outputs/saner/approach/phase3/tau{NN}/{level}/{scope}_patterns.json
    outputs/saner/approach/phase3/pattern_summary.json
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from hayalab.config import PathConfig

# --- Constants (hyperparameters tunable at the top of the file) ----
# 対象スコープ（phase0 の出力ファイル名と対応する）
SCOPES: tuple[str, ...] = ("sigma_1", "sigma_2", "sigma_3")

# 抽象度の水準
ABSTRACTION_LEVELS: tuple[str, ...] = ("alpha1", "alpha2")

# 一致度閾値の水準
THRESHOLDS: tuple[float, ...] = (0.7, 0.9)

# パターン仕様のスキーマ版（slow_patterns.json と揃える）
SPEC_VERSION: int = 1

# 任意のノードに一致するノード名（複数成分を束ねる根に用いる）
WILDCARD_NAME: str = "*"


# --- Helpers (only those called many times) ------------------------
def _entry_of(payload: dict[str, Any], scope: str, level: str, tau: float) -> dict[str, Any] | None:
    """1 クラスタ分の代表を 1 件のパターンエントリに変換する。

    成分が複数あるときは ``{"name": "*"}`` を根として補い、各成分を ``match: "descendant"`` の
    子として並べる。成分が 1 つならその成分をそのまま根にする。

    Args:
        payload: 代表 JSONL の 1 行。
        scope: スコープ名。
        level: 抽象度。
        tau: 一致度閾値。

    Returns:
        パターンエントリ。代表が空なら ``None``。
    """
    components = payload["patterns"]
    if not components:
        return None
    if len(components) == 1:
        root = components[0]
    else:
        root = {"name": WILDCARD_NAME, "children": [{**component, "match": "descendant"} for component in components]}
    cluster_id = payload["cluster_id"]
    return {
        "id": cluster_id,
        "key": f"{scope}_{level}_tau{round(tau * 10):02d}_c{cluster_id}",
        "description": f"cluster {cluster_id} ({payload['size']} members, {len(components)} components)",
        "components": len(components),
        "cluster_size": payload["size"],
        "root": root,
    }


# --- Main flow -----------------------------------------------------
if __name__ == "__main__":
    # --- Section 1: 引数とパスの解決 ---
    parser = argparse.ArgumentParser(description="build find_tree_matches pattern specs from cluster representatives")
    parser.add_argument("--scopes", nargs="+", default=list(SCOPES), help="対象スコープ")
    parser.add_argument("--levels", nargs="+", default=list(ABSTRACTION_LEVELS), help="抽象度の水準")
    parser.add_argument("--taus", type=float, nargs="+", default=list(THRESHOLDS), help="一致度閾値")
    parser.add_argument("--limit", type=int, default=0, help="1 セルあたり書き出すクラスタ数（0 で全件、要素数の多い順）")
    args = parser.parse_args()

    config = PathConfig()
    phase2_dir = config.outputs / "saner" / "approach" / "phase2"
    phase3_dir = config.outputs / "saner" / "approach" / "phase3"
    summary_path = phase2_dir / "representative_summary.json"

    if not summary_path.exists():
        raise FileNotFoundError(f"phase2 のサマリが見つかりません: {summary_path}")
    phase3_dir.mkdir(parents=True, exist_ok=True)

    with open(summary_path, encoding="utf-8") as f:
        ignore_names = json.load(f)["ignore_names"]
    print(f"Output: {phase3_dir}")
    print(f"scopes={args.scopes} levels={args.levels} taus={sorted(args.taus)} limit={args.limit or '全件'}\n")

    # --- Section 2: セルごとにパターン仕様を書き出す ---
    summary: list[dict[str, Any]] = []
    for tau in sorted(args.taus):
        suffix = f"tau{round(tau * 10):02d}"
        for level in args.levels:
            for scope in args.scopes:
                representative_path = phase2_dir / suffix / level / f"{scope}_representatives.jsonl"
                if not representative_path.exists():
                    print(f"[SKIP] {representative_path} が無い")
                    continue

                representatives = [json.loads(line) for line in open(representative_path, encoding="utf-8")]
                usable = [payload for payload in representatives if payload["patterns"]]
                # 要素数の多い順、同数はクラスタ ID 昇順で決定的に選ぶ
                selected = sorted(usable, key=lambda payload: (-payload["size"], payload["cluster_id"]))
                if args.limit:
                    selected = selected[: args.limit]
                entries = [entry for entry in (_entry_of(payload, scope, level, tau) for payload in selected) if entry is not None]

                cell_dir = phase3_dir / suffix / level
                cell_dir.mkdir(parents=True, exist_ok=True)
                output_path = cell_dir / f"{scope}_patterns.json"
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump({"version": SPEC_VERSION, "ignore_names": ignore_names, "patterns": entries}, f, ensure_ascii=False, indent=2)

                multi = sum(1 for entry in entries if entry["components"] > 1)
                summary.append(
                    {
                        "scope": scope,
                        "level": level,
                        "threshold": tau,
                        "representatives": len(representatives),
                        "empty": len(representatives) - len(usable),
                        "patterns": len(entries),
                        "wildcard_root": multi,
                    }
                )
                print(f"[{scope} {level} {suffix}] 代表 {len(representatives)} / 空 {len(representatives) - len(usable)} → パターン {len(entries)}（うち * 根 {multi}）")

    # --- Section 3: サマリの書き出し ---
    summary.sort(key=lambda row: (row["scope"], row["level"], row["threshold"]))
    output_path = phase3_dir / "pattern_summary.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"ignore_names": ignore_names, "cells": summary}, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(f"\nWritten: {output_path}")
