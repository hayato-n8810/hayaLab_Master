"""scam の slot 方式抽象化（ノード単位・cutout 単位・レコード単位）。

各関数は「1 ノード/cutout/レコード → 抽象化済み dict」の単体処理要素。
"""

from __future__ import annotations

from typing import Any

from .slot import (
    LITERAL_NUMBER_NAME,
    LITERAL_STRING_FRAGMENT_NAME,
    REGEX_NODE_NAME,
    allocate_slot,
    is_punctuation,
    match_identifier_prefix,
)


def abstract_node(
    node: dict[str, Any],
    level: int,
    slot_map: dict[str, str],
    in_regex: bool = False,
    is_formal_parameter_child: bool = False,
) -> dict[str, Any]:
    """1 ノードに ``level`` に応じた累積抽象化を適用する。

    累積階層の意味通り L1 → L2 の順に変換を重ねる。各レベルの判定はすべて関数冒頭で
    capture した ``original_name`` / ``original_value`` を参照するため、後段レベルが
    前段レベルの mutate 結果に影響されることはない。

    Args:
        node: 入力ノード dict (``cutouts.json`` スキーマ)。
        level: 抽象化レベル (1 または 2)。
        slot_map: 同一 cutout 内で共有する slot 割当辞書。
        in_regex: ``regex`` ノードの子孫（``parent`` に regex ノードの
            ``origin_index`` を含む）であれば True。
        is_formal_parameter_child: ``formal_parameters`` ノードの直接子であれば True。
            ``variadic`` フラグ値として直接反映される。

    Returns:
        抽象化済みノード dict。元の schema (``origin_index`` / ``begin`` /
        ``end`` / ``label`` / ``name`` / ``value`` / ``parent``) に
        ``slot_id`` と ``variadic`` を追加する。
    """
    original_name = node["name"]
    original_value = node["value"]

    name = original_name
    value: str = original_value
    slot_id: str | None = None
    variadic = is_formal_parameter_child

    # L1: identifier 値の slot 化（VAR_*/FUNCTION_* → $v* / $f*）
    prefix_match = match_identifier_prefix(original_value)
    if prefix_match is not None:
        marker = prefix_match[1]
        slot_id = allocate_slot(slot_map, original_value, marker)
        value = slot_id

    # L2: リテラル値の slot 化（number / string_fragment / regex 子孫）
    if level >= 2:
        if in_regex:
            slot_id = allocate_slot(slot_map, f"REGEX::{original_value}", "r")
            value = slot_id
        elif original_name == LITERAL_NUMBER_NAME:
            slot_id = allocate_slot(slot_map, f"NUMBER::{original_value}", "n")
            value = slot_id
        elif original_name == LITERAL_STRING_FRAGMENT_NAME:
            slot_id = allocate_slot(slot_map, f"STRING::{original_value}", "s")
            value = slot_id

    return {
        "origin_index": node["origin_index"],
        "begin": node["begin"],
        "end": node["end"],
        "label": node["label"],
        "name": name,
        "value": value,
        "parent": list(node["parent"]),
        "slot_id": slot_id,
        "variadic": variadic,
    }


def abstract_cutout(cutout: dict[str, Any], level: int) -> dict[str, Any]:
    """Cutout 単位で抽象化を適用する。 punctuation ノードは除外する。

    cutout 内の ``regex`` ノードと ``formal_parameters`` ノードの ``origin_index``
    集合を事前計算し、 各ノードに対して:

    * 子孫が regex の場合 → L2 で regex slot 化
    * 直接の親が ``formal_parameters`` の場合 → ``variadic = true``

    を判定するための情報を :func:`abstract_node` に渡す。

    Args:
        cutout: ``{"diff_node_indices": [...], "nodes": [...]}``。
        level: 抽象化レベル (1 または 2)。

    Returns:
        抽象化済み cutout dict。``diff_node_indices`` は punctuation 除外後に
        残った ``origin_index`` のみで再構成する。
    """
    slot_map: dict[str, str] = {}
    abstracted_nodes: list[dict[str, Any]] = []

    # regex ノードの origin_index 集合（regex 自身は子孫ではないため除外される）。
    regex_origin_indices: set[int] = {n["origin_index"] for n in cutout["nodes"] if n["name"] == REGEX_NODE_NAME}

    for node in cutout["nodes"]:
        if is_punctuation(node):
            continue
        in_regex = bool(regex_origin_indices.intersection(node["parent"]))
        abstracted_nodes.append(abstract_node(node, level, slot_map, in_regex))

    remaining_origin = {n["origin_index"] for n in abstracted_nodes}
    diff_indices = [i for i in cutout["diff_node_indices"] if i in remaining_origin]

    return {
        "diff_node_indices": diff_indices,
        "nodes": abstracted_nodes,
    }


def abstract_record(record: dict[str, Any], level: int) -> dict[str, Any]:
    """1 mb_id レコードを抽象化する（``abstract_level1`` / ``abstract_level2`` の共通実装）。

    Args:
        record: ``{"id": int, "cutouts": {depth: {...}}}``。
        level: 抽象化レベル (1 または 2)。

    Returns:
        抽象化済みレコード。
    """
    return {
        "id": record["id"],
        "cutouts": {depth: abstract_cutout(cutout, level) for depth, cutout in record["cutouts"].items()},
    }
