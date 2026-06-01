"""各idのcutout(depth)が所属するクラスとそのサイズを追跡する.

`classes_A0_M1.json` を入力とし, members に含まれる `{id}_{depth}`
(depth ∈ {Diff, Brother, ExParent, Parent}) を id ごとにまとめる.
各 id について, 各 depth が所属する class_id とそのクラスの size を出力する.

size > 1 のクラスに入っている depth は他の cutout と集約済み,
size == 1 (singleton) の depth は未集約と判別できる.

Usage:
    uv run python experiments/scam/RQ2/lest_size.py
    uv run python experiments/scam/RQ2/lest_size.py --input <path> --output <path>
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

# cutout の depth 種別 (出力順を固定する)
DEPTH_ORDER = ["Diff", "Brother", "ExParent", "Parent"]
DEPTH_SET = set(DEPTH_ORDER)

DEFAULT_INPUT = Path("outputs/scam/approach_temp_v2_jaccard_tau0.7/classes_A0_M1.json")
DEFAULT_OUTPUT = Path("outputs/scam/approach_temp_v2_jaccard_tau0.7/id_class_membership_A0_M1.json")


def split_member(member: str) -> tuple[str, str] | None:
    """member 文字列を (id, depth) に分解する.

    Args:
        member: "10040_Brother" のような `{id}_{depth}` 形式の文字列.

    Returns:
        (id, depth) のタプル. 末尾が既知の depth でない場合は None.
    """
    idx = member.rfind("_")
    if idx == -1:
        return None
    depth = member[idx + 1 :]
    if depth not in DEPTH_SET:
        return None
    return member[:idx], depth


def build_id_membership(classes: list[dict]) -> dict[str, dict]:
    """クラス一覧から id 単位の所属情報を構築する.

    Args:
        classes: classes_A0_M1.json をロードしたクラス辞書のリスト.
            各要素は少なくとも "class_id", "size", "members" を持つ.

    Returns:
        id -> {
            "depths": {depth: {"class_id": str, "class_size": int,
                               "class_unique_id": int}},
            "n_aggregated": int,   # size > 1 のクラスに入った depth 数
            "n_singleton": int,    # size == 1 のクラスに入った depth 数
        }
    """
    # id -> depth -> 所属情報
    membership: dict[str, dict[str, dict]] = defaultdict(dict)
    # class_id -> そのクラスに含まれるユニークな id 集合
    class_ids_count: dict[str, set[str]] = defaultdict(set)

    for cls in classes:
        class_id = cls["class_id"]
        for member in cls["members"]:
            parsed = split_member(member)
            if parsed is None:
                continue
            mb_id, _ = parsed
            class_ids_count[class_id].add(mb_id)

    for cls in classes:
        class_id = cls["class_id"]
        class_size = cls["size"]
        # members に登場するユニーク id 数 (例: 2_Brother,2_Parent,3_Brother -> 2)
        class_unique_id = len(class_ids_count[class_id])
        for member in cls["members"]:
            parsed = split_member(member)
            if parsed is None:
                continue
            mb_id, depth = parsed
            membership[mb_id][depth] = {
                "class_id": class_id,
                "class_size": class_size,
                "class_unique_id": class_unique_id,
            }

    result: dict[str, dict] = {}
    for mb_id, depths in membership.items():
        n_aggregated = sum(1 for info in depths.values() if info["class_size"] > 1)
        n_singleton = sum(1 for info in depths.values() if info["class_size"] == 1)
        # depth を固定順に整列
        ordered = {d: depths[d] for d in DEPTH_ORDER if d in depths}
        result[mb_id] = {
            "depths": ordered,
            "n_aggregated": n_aggregated,
            "n_singleton": n_singleton,
        }
    return result


def sort_key(mb_id: str) -> tuple[int, int | str]:
    """id を数値優先で安定ソートするためのキー."""
    if mb_id.isdigit():
        return (0, int(mb_id))
    return (1, mb_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="入力 classes_*.json のパス",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="出力 JSON のパス",
    )
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {args.input}")

    with args.input.open(encoding="utf-8") as f:
        classes = json.load(f)

    membership = build_id_membership(classes)

    # id を昇順に整列して出力 (再現性のため決定的順序)
    ordered_membership = {mb_id: membership[mb_id] for mb_id in sorted(membership, key=sort_key)}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(ordered_membership, f, ensure_ascii=False, indent=2)

    # サマリをコンソールに出力
    n_ids = len(ordered_membership)
    n_all_aggregated = sum(1 for v in ordered_membership.values() if v["n_singleton"] == 0 and v["n_aggregated"] > 0)
    n_partial = sum(1 for v in ordered_membership.values() if v["n_aggregated"] > 0 and v["n_singleton"] > 0)
    n_all_singleton = sum(1 for v in ordered_membership.values() if v["n_aggregated"] == 0 and v["n_singleton"] > 0)
    print(f"入力        : {args.input}")
    print(f"出力        : {args.output}")
    print(f"id 総数     : {n_ids}")
    print(f"  全depth集約: {n_all_aggregated}  (全cutoutが size>1 のクラス)")
    print(f"  一部集約   : {n_partial}  (集約と singleton が混在)")
    print(f"  全singleton: {n_all_singleton}  (全cutoutが size==1)")


if __name__ == "__main__":
    main()
