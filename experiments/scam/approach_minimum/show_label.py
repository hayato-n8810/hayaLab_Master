"""integrate クラスタの各メンバーに value 列を付与してクラスごとに列挙する。

入力:
    クラスタ結果: outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}/{depth}.json
        ``{"meta": {...}, "classes": {class_id: ["{id}_{depth}", ...]}}``
    抽象化:      outputs/scam/approach_minimum/abstract/abstract_level{L}.json
        ``[{"id": int, "cutouts": {depth: {"nodes": [...]}}}]``

処理:
    各クラスのメンバー ``"{id}_{depth}"`` について、対応する level・depth の cutout
    から value を ``_build_program_born`` で収集し、クラスごとに ``{id, value}`` を
    列挙する。

出力:
    outputs/scam/approach_minimum/integrate/{tau_dir}/level{L}/{depth}/{depth}_label.json
        ``{class_id: [{"id": int, "value": str}, ...]}``

実行例:
    uv run python experiments/scam/approach_minimum/show_label.py
    uv run python experiments/scam/approach_minimum/show_label.py --tau-dir jaccard07 --levels 0 1
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import hayalab
from hayalab.config import PathConfig

# cutout depth の順序（integrate / abstract と整合）。
DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")

# 終端ノード判定: ``"name: value [...]"`` 形式の label にマッチ。
_TERMINAL_LABEL_RE = re.compile(r"([^ ]+): (.+)")


def _build_program_born(nodes: list[dict[str, Any]]) -> dict[str, str]:
    """Cutout の nodes から終端ノードの value をスペース区切りで連結する。

    Args:
        nodes: cutout の ``nodes`` リスト。

    Returns:
        ``{"full": "<value value ...>"}``。label が ``"name: value"`` 形式
        （終端ノード）のもののみ value を採用する。
    """
    program_born_full = ""
    for node in nodes:
        if _TERMINAL_LABEL_RE.match(node["label"]):
            value = node["value"]
            program_born_full += f"{value} "
    return {"full": program_born_full}


def target_cutouts(data: list[dict[str, Any]], output_path: Path) -> None:
    """01_cutouts.json 形式（id ごとの cutouts スコープ集合）から label bone を構築する。

    Args:
        data: ``[{"id": int, "cutouts": {scope_name: {"nodes": [...]}}}]`` 形式のリスト。
        output_path: 出力先パス。

    出力構造:
        ``{id: {scope_name: {"full": str}}}``
    """
    result = {}
    for entry in data:
        entry_id = entry["id"]
        cutouts = entry["cutouts"]
        result[entry_id] = {scope_name: _build_program_born(scope["nodes"]) for scope_name, scope in cutouts.items()}

    hayalab.write_json(str(output_path), result)


def _member_to_mb_id(member: str) -> int:
    """cutout_id ``"{mb_id}_{depth}"`` から mb_id（int）を取り出す。

    depth 名にはアンダースコアが含まれないため、末尾の ``_{depth}`` を 1 回だけ
    分割して mb_id を得る。
    """
    mb_id_str, _depth = member.rsplit("_", 1)
    return int(mb_id_str)


def _labels_for_class(
    members: list[str],
    depth: str,
    id_to_cutouts: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """1 クラスのメンバー列から ``{id, value}`` の列を作る。

    Args:
        members: ``"{id}_{depth}"`` 形式の cutout_id リスト。
        depth: 対象 depth（このファイルの depth）。
        id_to_cutouts: mb_id → その mb の ``cutouts`` dict。

    Returns:
        ``[{"id": int, "value": str}, ...]``。メンバーの出現順を保つ。
    """
    rows: list[dict[str, Any]] = []
    for member in members:
        mb_id = _member_to_mb_id(member)
        cutouts = id_to_cutouts.get(mb_id, {})
        cutout = cutouts.get(depth)
        value = _build_program_born(cutout["nodes"])["full"] if cutout else ""
        rows.append({"id": mb_id, "value": value})
    return rows


def build_class_labels(
    cluster: dict[str, Any],
    depth: str,
    id_to_cutouts: dict[int, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """クラスタ結果 1 ファイル分から ``{class_id: [{id, value}, ...]}`` を作る。

    Args:
        cluster: integrate 出力 (``{"meta": ..., "classes": {...}}``)。
        depth: 対象 depth。
        id_to_cutouts: mb_id → cutouts のマップ。

    Returns:
        クラスごとの ``{id, value}`` 列辞書。クラスの順序は入力を保つ。
    """
    classes: dict[str, list[str]] = cluster.get("classes", {})
    return {class_id: _labels_for_class(members, depth, id_to_cutouts) for class_id, members in classes.items()}


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。"""
    parser = argparse.ArgumentParser(description="integrate クラスタに value 列を付与して列挙する")
    parser.add_argument(
        "--tau-dir",
        type=str,
        default="jaccard05",
        help="integrate 配下の tau ディレクトリ名 (default: jaccard05)",
    )
    parser.add_argument(
        "--levels",
        type=int,
        nargs="+",
        default=[0, 1, 2, 3],
        help="処理する抽象化レベル (default: 0 1 2 3)",
    )
    return parser.parse_args()


def main() -> None:
    """全 level・全 depth のクラスタに value を付与して ``{depth}_label.json`` を書き出す。"""
    args = parse_args()
    config = PathConfig()

    base = config.outputs / "scam" / "approach_minimum"
    abstract_dir = base / "abstract"
    integrate_dir = base / "integrate" / args.tau_dir

    for level in args.levels:
        abstract_path = abstract_dir / f"abstract_level{level}.json"
        if not abstract_path.exists():
            print(f"[SKIP] abstract not found: {abstract_path}", flush=True)
            continue
        print(f"[ABSTRACT] {abstract_path}", flush=True)
        # level ファイルは 1 回だけ読み、4 depth で使い回す（巨大ファイルの再読込回避）。
        records = hayalab.read_json(str(abstract_path))
        id_to_cutouts: dict[int, dict[str, Any]] = {entry["id"]: entry["cutouts"] for entry in records}

        for depth in DEPTHS:
            cluster_path = integrate_dir / f"level{level}" / f"{depth}" / f"{depth}.json"
            if not cluster_path.exists():
                print(f"[SKIP] cluster not found: {cluster_path}", flush=True)
                continue
            cluster = hayalab.read_json(str(cluster_path))
            class_labels = build_class_labels(cluster, depth, id_to_cutouts)

            out_path = integrate_dir / f"level{level}" / f"{depth}" / f"{depth}_label.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            hayalab.write_json(str(out_path), class_labels)
            print(f"[OUTPUT] {out_path}  (classes={len(class_labels)})", flush=True)


if __name__ == "__main__":
    main()
