"""パターン抽出パイプライン Stage 2: 抽象化 (3 段階 A1/A2/A3 = 0/1/2)。

抽象化レベルは下位レベルを内包する単調設計。`abst_level` は整数 0/1/2:

| level | 名称 | 適用内容 |
|---|---|---|
| 0 (A1) | 既存正規化のまま | 識別子は前段で `VAR_N` / `FUNCTION_N` 等に prefix-番号 正規化済み。 |
|         |                  | リテラルは具体値、ノード名もそのまま |
| 1 (A2) | + リテラル汎化  | `LITERAL_TYPE_MAP` のリテラル (数値/文字列/真偽値/null/regex) を |
|         |                  | `NUM`/`STR`/`BOOL`/`NULL`/`REGEX` 型クラスに置換 (Type-2 clone 流) |
| 2 (A3) | + 意味的汎化    | A2 に加えて以下を適用: |
|         |                  | ① 関数種別統一: `FUNCTION_LIKE_TYPES` (7 種) を共通ラベル |
|         |                  |    `FUNCTION_LIKE` に置換 (role-based token abstraction) |
|         |                  | ② variadic マーカ: `VARIADIC_CONTAINER_TYPES` |
|         |                  |    (`arguments` / `formal_parameters`) のノードに |
|         |                  |    `variadic: True` を付与。検出側はこのマーカが付いた |
|         |                  |    子リストにのみ順序保存部分列マッチを適用 (Baker 1995) |

検出側 (`detect.py`) は識別子値比較を**全レベルで prefix-only 一致に固定**する。
slot/backreference (theta) 同一性も全レベル維持。

入力は `experiments/scam/approach/01_cutout.py` の新スキーマに準拠した dict:
    {"diff_node_indices": list[int], "nodes": list[{"origin_index", "begin", "end",
     "label", "name", "value", "parent"}]}

公開 API:
    - abstract_cutout(cutout_entry, mb_id, depth, abst_level): Pattern
    - compute_signature(ast_template): str
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from hayalab.classes.pattern import Pattern
from hayalab.config.pattern_config import (
    FUNCTION_LIKE_LABEL,
    FUNCTION_LIKE_TYPES,
    IDENTIFIER_NODE_TYPES,
    IDENTIFIER_PREFIXES,
    LITERAL_TYPE_MAP,
    PROTO_RECV_LABEL,
    VARIADIC_CONTAINER_TYPES,
)


def _detect_identifier_prefix(value: str) -> str | None:
    """Value の先頭プレフィクス（VAR/KEY/FUNCTION/CLASS）を返す。なければ None。"""
    for prefix_str, prefix_class in IDENTIFIER_PREFIXES.items():
        if value.startswith(prefix_str):
            return prefix_class
    return None


def _is_terminal_label(label: str, name: str) -> bool:
    """終端ノードか判定する (label が `name: value ...` 形式)。"""
    return label.startswith(f"{name}: ")


def _abstract_node_from_payload(
    node_payload: dict[str, Any],
    abst_level: int,
    slot_lookup: dict[str, int],
) -> dict[str, Any]:
    """新スキーマの node payload を抽象化レベルに従って template dict に変換する。

    Args:
        node_payload: {"origin_index", "name", "value", "label", "parent", ...} を持つ dict。
        abst_level: 0=A1 (原型), 1=A2 (+リテラル汎化), 2=A3 (+意味的汎化)。
        slot_lookup: original_value → slot_id のマップ（呼び出し側で構築・更新）。

    Returns:
        ast_template の 1 要素となる dict。`variadic` フィールドは A3 で
        VARIADIC_CONTAINER_TYPES に該当する場合 True、それ以外 False。
    """
    idx = node_payload["origin_index"]
    name = node_payload["name"]
    value = node_payload["value"]
    label = node_payload["label"]
    slot_id: int | None = None
    prefix: str | None = None
    original_value: str | None = None
    is_terminal = _is_terminal_label(label, name)
    variadic = False

    # ── 識別子: 全レベルで slot_id/prefix/original_value を保持（マッチ規則は detect 側で prefix-only に固定） ──
    if name in IDENTIFIER_NODE_TYPES:
        prefix = _detect_identifier_prefix(value)
        if prefix is not None:
            original_value = value
            slot_id = slot_lookup.setdefault(value, len(slot_lookup) + 1)

    # ── A2 以上: リテラル汎化 (型クラス置換) ──
    elif abst_level >= 1 and name in LITERAL_TYPE_MAP:
        abstract_label = LITERAL_TYPE_MAP[name]
        name = abstract_label
        value = abstract_label

    # ── A3: 関数種別統一 ──
    if abst_level >= 2 and name in FUNCTION_LIKE_TYPES:
        name = FUNCTION_LIKE_LABEL
        value = FUNCTION_LIKE_LABEL

    # ── A3: variadic マーカ ──
    if abst_level >= 2 and node_payload["name"] in VARIADIC_CONTAINER_TYPES:
        variadic = True

    return {
        "origin_index": idx,
        "name": name,
        "value": value,
        "slot_id": slot_id,
        "prefix": prefix,
        "original_value": original_value,
        "is_terminal": is_terminal,
        "variadic": variadic,
    }


def _identify_proto_recv_collapse(nodes: list[dict[str, Any]], abst_level: int) -> tuple[set[int], set[int]]:
    """A3 で receiver サブツリーを PROTO_RECV に縮約する対象を特定する。

    対象:
        - `member_expression` で右側子が `property_identifier(value="prototype")` のもの
          (例: `Object.prototype`, `Array.prototype`)
        - 子を持たない `object` (空オブジェクトリテラル `{}`)
        - 子を持たない `array` (空配列リテラル `[]`)

    Args:
        nodes: cutout の生 nodes 列。
        abst_level: 0 or 1 のときは縮約しない。

    Returns:
        (collapse_root_origin_indices, descendant_origin_indices)
        - 前者: 名前を `PROTO_RECV_LABEL` に置換するルート群 (template に残す)。
        - 後者: 縮約されたサブツリーの子孫群 (template から取り除く)。
    """
    if abst_level < 2:
        return set(), set()

    by_idx: dict[int, dict[str, Any]] = {n["origin_index"]: n for n in nodes}
    children: dict[int, list[int]] = {}
    for n in nodes:
        parent_chain = n.get("parent", [])
        if parent_chain:
            children.setdefault(parent_chain[-1], []).append(n["origin_index"])

    def _descendants(root_idx: int) -> set[int]:
        out: set[int] = set()
        stack = [root_idx]
        while stack:
            x = stack.pop()
            for c in children.get(x, []):
                if c not in out:
                    out.add(c)
                    stack.append(c)
        return out

    collapse_roots: set[int] = set()
    to_remove: set[int] = set()

    # 親側から走査する保証はないが、最終的に `collapse_roots -= to_remove` で
    # 上位サブツリーに飲み込まれたルートを取り除くため順序非依存。
    for n in nodes:
        idx = n["origin_index"]
        name = n["name"]
        kids = children.get(idx, [])

        if name == "member_expression":
            for k in kids:
                kn = by_idx.get(k)
                if kn is not None and kn["name"] == "property_identifier" and kn.get("value") == "prototype":
                    collapse_roots.add(idx)
                    to_remove |= _descendants(idx)
                    break
        elif name in ("object", "array"):
            empty_tokens = {"{", "}"} if name == "object" else {"[", "]"}
            # 実体的に空 (子が brace/bracket トークンだけ) なら縮約対象
            if all((by_idx.get(k) or {}).get("name") in empty_tokens for k in kids):
                collapse_roots.add(idx)
                to_remove |= _descendants(idx)

    # 別の collapse_root の子孫だったルートは取り除く (上位が PROTO_RECV にまとめるため)
    collapse_roots -= to_remove
    return collapse_roots, to_remove


def compute_signature(ast_template: list[dict]) -> str:
    """ast_template から決定論的にハッシュ署名を計算する。

    Args:
        ast_template: 抽象化済みノードの dict 列（ノード origin_index 昇順）。

    Returns:
        SHA-256 の先頭 16 文字。
    """
    serializable = []
    for tn in ast_template:
        serializable.append(
            {
                "name": tn["name"],
                "value": tn["value"],
                "parent_relative": tn.get("parent_relative", []),
                "slot_id": tn.get("slot_id"),
                "variadic": tn.get("variadic", False),
            }
        )
    payload = json.dumps(serializable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def abstract_cutout(
    cutout_entry: dict[str, Any],
    mb_id: int,
    depth: str,
    abst_level: int,
) -> Pattern:
    """新スキーマ cutout 1 つに抽象化を適用してパターンを生成する。

    Args:
        cutout_entry: 01_cutouts.json の cutouts.{Diff,Brother,...} 1 つ分の dict。
            `{"diff_node_indices": [...], "nodes": [full payload, ...]}` を期待する。
        mb_id: 由来 MB の id。
        depth: 切り出し粒度名 ("Diff" / "Brother" / "ExParent" / "Parent")。
        abst_level: 抽象化レベル (0=A1, 1=A2, 2=A3)。

    Returns:
        抽象化適用後のパターン。signature は決定論的に計算される。

    Raises:
        ValueError: abst_level が 0..2 の範囲外、もしくは nodes が空。
    """
    if abst_level not in (0, 1, 2):
        raise ValueError(f"abst_level must be one of 0..2, got {abst_level}")
    nodes = cutout_entry.get("nodes", [])
    if not nodes:
        raise ValueError("cutout_entry has no nodes")

    # A3: receiver 縮約対象を特定 (collapse_root は残し、子孫は template から除外)
    collapse_roots, to_remove = _identify_proto_recv_collapse(nodes, abst_level)
    kept_nodes = [n for n in nodes if n["origin_index"] not in to_remove]

    # 元 AST index → cutout 内 local index (kept_nodes での出現順)
    index_to_local: dict[int, int] = {n["origin_index"]: i for i, n in enumerate(kept_nodes)}

    # 識別子 slot 割り当て: original_value → slot_id（Cutout 内で出現順に 1, 2, ...）
    slot_lookup: dict[str, int] = {}

    ast_template: list[dict] = []
    for n in kept_nodes:
        if n["origin_index"] in collapse_roots:
            # PROTO_RECV ノードに置換 (variadic=True で子の差異を吸収)
            tn = {
                "origin_index": n["origin_index"],
                "name": PROTO_RECV_LABEL,
                "value": PROTO_RECV_LABEL,
                "slot_id": None,
                "prefix": None,
                "original_value": None,
                "is_terminal": True,
                "variadic": True,
            }
        else:
            tn = _abstract_node_from_payload(n, abst_level, slot_lookup)
        # 元 AST の parent 列を Cutout 内 local index 列にマップ
        # (Cutout 外の祖先・collapse で除外された子孫はスキップ)
        tn["parent_relative"] = [index_to_local[p] for p in n.get("parent", []) if p in index_to_local]
        ast_template.append(tn)

    signature = compute_signature(ast_template)

    return Pattern(
        mb_id=mb_id,
        depth=depth,
        abst_level=abst_level,
        ast_template=ast_template,
        signature=signature,
    )
