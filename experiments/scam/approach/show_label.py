"""integrate クラスタの各メンバーに value 列を付与してクラスごとに列挙する。

入力:
    クラスタ結果: outputs/scam/approach/integrate/{tau_dir}/level{L}/{depth}/{depth}.json
        ``{"meta": {...}, "classes": {class_id: ["{id}_{depth}", ...]}}``
    抽象化:      outputs/scam/approach/abstract/abstract_level{L}.json
        ``[{"id": int, "cutouts": {depth: {"nodes": [...]}}}]``

処理:
    各クラスのメンバー ``"{id}_{depth}"`` について、対応する level・depth の cutout
    から終端ノード（``"name: value"`` 形式の label を持つノード）の value を空白区切りで
    連結し、クラスごとに ``{id, value}`` を列挙する。

出力:
    outputs/scam/approach/integrate/{tau_dir}/level{L}/{depth}/{depth}_label.json
        ``{class_id: [{"id": int, "value": str}, ...]}``

実行例:
    uv run python experiments/scam/approach/show_label.py
    uv run python experiments/scam/approach/show_label.py --tau-dir jaccard07 --levels 1 2
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import hayalab
from hayalab.config import PathConfig

# sibling import: 同じ approach/ 内の integrate.py から member_to_mb_id を共有する。
_APPROACH_DIR = Path(__file__).resolve().parent
if str(_APPROACH_DIR) not in sys.path:
    sys.path.insert(0, str(_APPROACH_DIR))

from integrate import DEPTHS, member_to_mb_id  # noqa: E402  -- sibling import 後

# 終端ノード判定: ``"name: value [...]"`` 形式の label にマッチ。
_TERMINAL_LABEL_RE = re.compile(r"([^ ]+): (.+)")


def _labels_for_class(
    members: list[str],
    depth: str,
    id_to_cutouts: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """1 クラスのメンバー列から ``{id, value}`` の列を作る。

    各メンバーの value は cutout の終端ノード（label が ``"name: value"`` 形式）の
    value をスペース区切りで連結した文字列。

    Args:
        members: ``"{id}_{depth}"`` 形式の cutout_id リスト。
        depth: 対象 depth（このファイルの depth）。
        id_to_cutouts: mb_id → その mb の ``cutouts`` dict。

    Returns:
        ``[{"id": int, "value": str}, ...]``。メンバーの出現順を保つ。
    """
    rows: list[dict[str, Any]] = []
    for member in members:
        mb_id = member_to_mb_id(member)
        cutouts = id_to_cutouts.get(mb_id, {})
        cutout = cutouts.get(depth)
        if cutout:
            value = "".join(f"{node['value']} " for node in cutout["nodes"] if _TERMINAL_LABEL_RE.match(node["label"]))
        else:
            value = ""
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
        default=[1, 2],
        help="処理する抽象化レベル (default: 1 2)",
    )
    return parser.parse_args()


def main() -> None:
    """全 level・全 depth のクラスタに value を付与して ``{depth}_label.json`` を書き出す。"""
    args = parse_args()
    config = PathConfig()

    base = config.outputs / "scam" / "approach"
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
