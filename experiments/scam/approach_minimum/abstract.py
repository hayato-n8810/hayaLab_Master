"""Stage 3: 抽象化レベル L0–L3 を cutouts.json に適用する (approach_minimum)。

``docs/abstract.md`` で確定した 4 段階累積階層 (L0/L1/L2/L3) を mb_id 単位で
各 cutout に適用し、レベル別に JSON ファイルとして書き出す。設計の背景・
関連研究との対応は ``docs/abstraction_design.md`` を参照。

Levels:
    L0 (Skeleton):     identifier 値 (VAR_/FUNCTION_) を slot 化。
    L1 (Standard):     L0 + literal 値 (number / string_fragment) を slot 化。
                       さらに ``regex`` ノード配下（regex ノードの origin_index
                       を parent に含む全ノード）の値を ``$r0`` 形式の slot に
                       置換する（削除はしない）。
    L2 (Rewritten):    L1 + 非終端 collapse (function_like / var_decl_stmt /
                       var_decl_kw)。
    L3 (Generalized):  L2 + API 名抽象化 (``property_identifier`` の値を
                       ``$api`` に置換)。

paper (SCAM2026) における位置付け:
    本研究の確定方針 (paper §6.3.1) は「**抽象化 (Type-2 段階)
    × 類似度 (Type-3 相当の τ) の 2 軸で粒度を制御する**」設計を採用する。
    メイン分析は **L0 / L1 のみ** を用い、 Type-3 相当の柔軟性は τ 軸
    (integrate.py の ``--taus``) で吸収する。 文献的には Roy survey の
    Type-2 / SourcererCC (Sajnani 2016) の overlap threshold の系譜に対応。

    L2 / L3 のコードは **paper §6.3.1 で「不採用」 を実証するための
    再現性確保** として残置している (E2 §4.2.2 の L1↔L2 等価性、
    E4 §5.3 の L3 擬似クラスタ問題)。 run.sh のデフォルトでは L2/L3 は
    実行されない。 これらを再走したい場合のみ ``--levels 0 1 2 3`` を
    明示指定する。

演算子・キーワード (``===``, ``!==``, ``==``, ``%`` 等) は全レベルで保持する。
Punctuation (``(``, ``)``, ``,``, ``.`` 等) は文献的標準に従い抽象化結果から
除外する。それ以外のサブツリー削除は採用しない（``docs/abstract.md`` §2.2）。

``variadic`` フラグは ``formal_parameters`` の直接子 (``parent[-1]`` が
``formal_parameters`` の ``origin_index``) にのみ立てる。抽象化レベルに依存せず
L0 から true となる（``docs/abstract.md`` §3 variadic フラグ）。

Input:
    outputs/scam/approach_minimum/cutouts.json

Output:
    outputs/scam/approach_minimum/abstract/abstract_level{0,1,2,3}.json

Example:
    uv run python experiments/scam/approach_minimum/abstract.py --workers 8
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

import hayalab
from hayalab.config import PathConfig

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cutout の depth 順序（出力スキーマ安定化のため保持）。
DEPTHS: tuple[str, ...] = ("Diff", "Brother", "ExParent", "Parent")

# 抽象化結果から除外する汎用記号集合
PUNCTUATION_NAMES: frozenset[str] = frozenset(["(", ")", ",", ".", ";", "{", "}", "[", "]", ":", '"', "'", "_"])

# 入力 ``01_cutouts.json`` の前処理 (``hayalab.abst``) で割り当てられる
# identifier prefix → slot family marker の対応。
IDENTIFIER_PREFIXES: tuple[tuple[str, str], ...] = (
    ("VAR_", "v"),
    ("FUNCTION_", "f"),
)

# L1 でリテラル抽象化対象となる tree-sitter ノード名。
LITERAL_NUMBER_NAME: str = "number"
LITERAL_STRING_FRAGMENT_NAME: str = "string_fragment"

# L1 で regex 配下抽象化のトリガーとなる tree-sitter ノード名。
REGEX_NODE_NAME: str = "regex"

# variadic フラグ判定の親ノード名。``formal_parameters`` の直接子に limited
# scope で variadic=true を立てる（``docs/abstract.md`` §3 variadic フラグ）。
FORMAL_PARAMETERS_NAME: str = "formal_parameters"

# L2 で ``function_like`` に collapse する非終端集合。
# 注意: ``"function"`` は本プロジェクトの tree-sitter-javascript バージョンで
# 無名関数式 (anonymous function expression) の kind として出現する。同 name は
# ``function`` keyword の terminal token でも使われるため、L2 collapse 適用時は
# label の ``":"`` 有無で terminal を除外する必要がある (:func:`_abstract_node`)。
FUNCTION_LIKE_NAMES: frozenset[str] = frozenset(
    [
        "function",
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "generator_function",
        "generator_function_declaration",
    ]
)
FUNCTION_LIKE_TOKEN: str = "function_like"

# L2 で ``var_decl_stmt`` に collapse する宣言文非終端。
VAR_DECL_STMT_NAMES: frozenset[str] = frozenset(["variable_declaration", "lexical_declaration"])
VAR_DECL_STMT_TOKEN: str = "var_decl_stmt"

# L2 で ``var_decl_kw`` に collapse する宣言キーワード。
VAR_DECL_KW_NAMES: frozenset[str] = frozenset(["var", "let", "const"])
VAR_DECL_KW_TOKEN: str = "var_decl_kw"

# L3 で API 名抽象化対象となる tree-sitter ノード名。
API_NODE_NAME: str = "property_identifier"
API_TOKEN: str = "$api"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_punctuation(node: dict[str, Any]) -> bool:
    """Punctuation ノードか判定する。

    Args:
        node: 入力ノード dict (``name`` / ``value`` を含む)。

    Returns:
        ``name`` または ``value`` が :data:`PUNCTUATION_NAMES` に含まれる場合 True。
    """
    return node["name"].strip() in PUNCTUATION_NAMES or node["value"].strip() in PUNCTUATION_NAMES


def _match_identifier_prefix(value: str) -> Optional[tuple[str, str]]:
    """Identifier prefix にマッチした場合 ``(prefix, marker)`` を返す。

    Args:
        value: ノードの ``value`` 文字列。

    Returns:
        例: ``"VAR_3"`` → ``("VAR_", "v")``。マッチしなければ ``None``。
    """
    for prefix, marker in IDENTIFIER_PREFIXES:
        if value.startswith(prefix):
            return prefix, marker
    return None


def _allocate_slot(slot_map: dict[str, str], key: str, marker: str) -> str:
    """Slot ID を割り当てる（同一 key は同一 slot を再利用）。

    Args:
        slot_map: 同一 cutout 内で共有する mutable な slot 割当辞書。
        key: 元値（cache キー）。
        marker: slot family を示す 1 文字 (``v`` / ``f`` / ``n`` / ``s`` / ``r``)。

    Returns:
        ``$v0`` / ``$n1`` 等の slot ID。
    """
    if key in slot_map:
        return slot_map[key]
    count = sum(1 for v in slot_map.values() if v.startswith(f"${marker}"))
    slot_id = f"${marker}{count}"
    slot_map[key] = slot_id
    return slot_id


def _abstract_node(
    node: dict[str, Any],
    level: int,
    slot_map: dict[str, str],
    in_regex: bool = False,
    is_formal_parameter_child: bool = False,
) -> dict[str, Any]:
    """1 ノードに ``level`` に応じた累積抽象化を適用する。

    累積階層の意味通り L0 → L1 → L2 → L3 の順に変換を重ねる。各レベルの判定は
    すべて関数冒頭で capture した ``original_name`` / ``original_value`` を参照
    するため、後段レベルが前段レベルの mutate 結果に影響されることはない。
    L2 と L3 は対象ノード種別が排他的 (L2: function*/declaration 系、L3:
    property_identifier) であり、両者を入れ替えても結果は変わらない。

    Args:
        node: 入力ノード dict (``01_cutouts.json`` スキーマ)。
        level: 抽象化レベル (0..3)。
        slot_map: 同一 cutout 内で共有する slot 割当辞書。
        in_regex: ``regex`` ノードの子孫（``parent`` に regex ノードの
            ``origin_index`` を含む）であれば True。L1 以降で regex slot
            ``$r*`` に置換するためのフラグ。
        is_formal_parameter_child: ``formal_parameters`` ノードの直接子
            （``parent[-1]`` が ``formal_parameters`` の ``origin_index``）で
            あれば True。``variadic`` フラグ値として直接反映される
            (``docs/abstract.md`` §3 variadic フラグ)。

    Returns:
        抽象化済みノード dict。元の schema (``origin_index`` / ``begin`` /
        ``end`` / ``label`` / ``name`` / ``value`` / ``parent``) に
        ``slot_id`` と ``variadic`` を追加する。
    """
    original_name = node["name"]
    original_value = node["value"]

    # 出力フィールド初期値: 抽象化されなければ元の name/value をそのまま返す。
    name = original_name
    value: str = original_value
    slot_id: Optional[str] = None
    # variadic は grammar-level の構造的性質として formal_parameters の直接子に限定して true にする。抽象化レベルには依存しない (L0 から立つ)。
    variadic = is_formal_parameter_child

    # ---- L0: identifier 値の slot 化 -------------------------------------
    # 前処理出力の VAR_*/FUNCTION_* を cutout 内で ``$v0`` / ``$f0`` 形式に
    # 再採番する。
    prefix_match = _match_identifier_prefix(original_value)
    if prefix_match is not None:
        marker = prefix_match[1]
        slot_id = _allocate_slot(slot_map, original_value, marker)
        value = slot_id

    # ---- L1: リテラル値の slot 化 ----------------------------------------
    # number / string_fragment / regex 子孫を ``$n*`` / ``$s*`` / ``$r*`` に
    # 置換する。regex 子孫判定は具体ノード種別より優先する。
    if level >= 1:
        if in_regex:
            slot_id = _allocate_slot(slot_map, f"REGEX::{original_value}", "r")
            value = slot_id
        elif original_name == LITERAL_NUMBER_NAME:
            slot_id = _allocate_slot(slot_map, f"NUMBER::{original_value}", "n")
            value = slot_id
        elif original_name == LITERAL_STRING_FRAGMENT_NAME:
            slot_id = _allocate_slot(slot_map, f"STRING::{original_value}", "s")
            value = slot_id

    # ---- L2: 非終端 / キーワード collapse ---------------------------------
    # function-like / 変数宣言文 / 宣言キーワードをそれぞれ単一 token に統合。
    # ``name="function"`` は無名関数式の非終端と ``function`` keyword terminal
    # の両方で使われるため、後者 (label に ``":"`` を含む) を除外する。
    # variadic フラグはここでは触らない
    if level >= 2:
        is_function_keyword_terminal = original_name == "function" and ":" in node["label"]
        if original_name in FUNCTION_LIKE_NAMES and not is_function_keyword_terminal:
            name = FUNCTION_LIKE_TOKEN
        elif original_name in VAR_DECL_STMT_NAMES:
            name = VAR_DECL_STMT_TOKEN
        elif original_name in VAR_DECL_KW_NAMES:
            name = VAR_DECL_KW_TOKEN
            value = VAR_DECL_KW_TOKEN

    # ---- L3: API 名抽象化 -------------------------------------------------
    # ``property_identifier`` ノードの value を ``$api`` に置換する。
    if level >= 3 and original_name == API_NODE_NAME:
        value = API_TOKEN
        slot_id = API_TOKEN

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


def _abstract_cutout(cutout: dict[str, Any], level: int) -> dict[str, Any]:
    """Cutout 単位で抽象化を適用する。punctuation ノードは除外する。

    cutout 内の ``regex`` ノードと ``formal_parameters`` ノードの
    ``origin_index`` 集合を事前計算し、各ノードに対して:

    * 子孫が regex の場合 → L1 で regex slot 化
    * 直接の親が ``formal_parameters`` の場合 → ``variadic = true``

    を判定するための情報を :func:`_abstract_node` に渡す。

    Args:
        cutout: ``{"diff_node_indices": [...], "nodes": [...]}``。
        level: 抽象化レベル (0..3)。

    Returns:
        抽象化済み cutout dict。``diff_node_indices`` は punctuation 除外後に
        残った ``origin_index`` のみで再構成する。
    """
    slot_map: dict[str, str] = {}
    abstracted_nodes: list[dict[str, Any]] = []

    # regex ノードの origin_index 集合（regex 自身は子孫ではないため除外される）。
    regex_origin_indices: set[int] = {n["origin_index"] for n in cutout["nodes"] if n["name"] == REGEX_NODE_NAME}
    # formal_parameters ノードの origin_index 集合。直接の親判定に用いる。
    formal_parameters_origin_indices: set[int] = {n["origin_index"] for n in cutout["nodes"] if n["name"] == FORMAL_PARAMETERS_NAME}

    for node in cutout["nodes"]:
        if _is_punctuation(node):
            continue
        in_regex = bool(regex_origin_indices.intersection(node["parent"]))
        parent_last = node["parent"][-1] if node["parent"] else None
        is_formal_parameter_child = parent_last in formal_parameters_origin_indices
        abstracted_nodes.append(
            _abstract_node(
                node,
                level,
                slot_map,
                in_regex,
                is_formal_parameter_child,
            )
        )

    remaining_origin = {n["origin_index"] for n in abstracted_nodes}
    diff_indices = [i for i in cutout["diff_node_indices"] if i in remaining_origin]

    return {
        "diff_node_indices": diff_indices,
        "nodes": abstracted_nodes,
    }


def _abstract_record(record: dict[str, Any], level: int) -> dict[str, Any]:
    """1 mb_id レコードを抽象化する（``abstract_levelN`` の共通実装）。

    Args:
        record: ``{"id": int, "cutouts": {depth: {...}}}``。
        level: 抽象化レベル (0..3)。

    Returns:
        抽象化済みレコード。
    """
    return {
        "id": record["id"],
        "cutouts": {depth: _abstract_cutout(cutout, level) for depth, cutout in record["cutouts"].items()},
    }


# ---------------------------------------------------------------------------
# Public level functions (each implemented as a single function per spec)
# ---------------------------------------------------------------------------


def abstract_level0(record: dict[str, Any]) -> dict[str, Any]:
    """L0 (Skeleton): identifier 値のみを cutout 内で slot 化する。

    前処理で割り当てられた ``VAR_*`` / ``FUNCTION_*`` を cutout 内で一貫した
    ``$v0`` / ``$f0`` 形式の slot ID に再採番する。リテラル・API 名・演算子・
    非終端は全て保持する。

    Args:
        record: 1 mb_id 分の cutout 集合 (``{"id", "cutouts"}``)。

    Returns:
        L0 抽象化済みレコード。
    """
    return _abstract_record(record, 0)


def abstract_level1(record: dict[str, Any]) -> dict[str, Any]:
    """L1 (Standard): L0 + リテラル値の slot 化（regex 子孫含む）。

    ``number`` / ``string_fragment`` ノードの値を ``$n0`` / ``$s0`` 形式の
    slot ID に置換する。さらに ``regex`` ノードの ``origin_index`` を
    ``parent`` に含む全ノード（regex 子孫）の値を ``$r0`` 形式の slot ID に
    置換する。regex 子孫は**削除せず slot 化**する方針 (``docs/abstract.md``
    §2.2)。Tiarks Type-2.3 を regex リテラルへ拡張した形となる。

    Args:
        record: 1 mb_id 分の cutout 集合 (``{"id", "cutouts"}``)。

    Returns:
        L1 抽象化済みレコード。
    """
    return _abstract_record(record, 1)


def abstract_level2(record: dict[str, Any]) -> dict[str, Any]:
    """L2 (Rewritten): L1 + 非終端 collapse。

    以下の collapse を追加で適用する:

    * ``function_declaration`` / ``function_expression`` / ``arrow_function``
      / ``method_definition`` / ``generator_function*`` → ``function_like``
    * ``variable_declaration`` / ``lexical_declaration`` → ``var_decl_stmt``
    * ``var`` / ``let`` / ``const`` キーワード → ``var_decl_kw``

    API 名と演算子・キーワード (``===`` / ``!==`` / ``==`` / ``%`` 等) は
    依然として保持する。

    Args:
        record: 1 mb_id 分の cutout 集合 (``{"id", "cutouts"}``)。

    Returns:
        L2 抽象化済みレコード。
    """
    return _abstract_record(record, 2)


def abstract_level3(record: dict[str, Any]) -> dict[str, Any]:
    """L3 (Generalized): L2 + API 名抽象化。

    ``property_identifier`` ノードの値を ``$api`` に置換する。
    演算子・キーワードおよびその他の identifier は保持。

    Args:
        record: 1 mb_id 分の cutout 集合 (``{"id", "cutouts"}``)。

    Returns:
        L3 抽象化済みレコード。
    """
    return _abstract_record(record, 3)


# 抽象化レベル → トップレベル関数の対応表。ProcessPoolExecutor で pickling
# する都合上、モジュールトップに置いた純関数を参照する。
LEVEL_FUNCTIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    0: abstract_level0,
    1: abstract_level1,
    2: abstract_level2,
    3: abstract_level3,
}


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """CLI 引数を解析する。"""
    parser = argparse.ArgumentParser(description="Stage 3: abstraction L0..L3 (mb_id 並列)")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="入力 cutouts.json のパス (省略時はデフォルトパス)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="出力ディレクトリ (省略時は outputs/scam/approach_minimum/abstract/)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="並列化数 (mb_id 単位で並列処理)。1 以下で逐次処理。",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help=("server モード: 4 レベル × mb_id の全タスクを共有プールへ同時投入し 最大限並列化する（4 レベル分の結果を同時にメモリ保持）。大メモリ・多コア環境向け。"),
    )
    return parser.parse_args()


def _run_level_sequential(records: list[dict[str, Any]], level: int, output_dir: Path) -> Path:
    """1 レベルを逐次処理し、結果ファイルを書き出す。

    Args:
        records: 入力 mb_id レコード列。
        level: 抽象化レベル (0..3)。
        output_dir: 出力ディレクトリ。

    Returns:
        書き出した JSON のパス。
    """
    fn = LEVEL_FUNCTIONS[level]
    results = [fn(r) for r in records]
    output_path = output_dir / f"abstract_level{level}.json"
    hayalab.write_json(str(output_path), results)
    return output_path


def _run_server(
    records: list[dict[str, Any]],
    levels: tuple[int, ...],
    output_dir: Path,
    workers: int,
) -> None:
    """Server モード: 4 レベル × mb_id の全タスクを同時投入して最大限並列化する。

    全レベル・全レコードの抽象化タスクを 1 つの共有 ProcessPoolExecutor へ一括で
    submit し、レベル境界で並列度が落ちるのを避けて CPU を常時フル稼働させる。
    全 future の結果（4 レベル分）を完了まで同時にメモリ保持するため、大メモリ
    環境を前提とする。書き出しはレベル昇順・id 昇順（submit 順）を維持する。

    Args:
        records: 入力 mb_id レコード列。
        levels: 抽象化レベルのタプル (0..3)。
        output_dir: 出力ディレクトリ。
        workers: 並列ワーカー数。
    """
    print("[MODE] server (全レベル同時投入・結果メモリ保持)", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        # レベル昇順・records 順に submit するため、各 future リストは入力順を保つ。
        futures_per_level: dict[int, list] = {level: [pool.submit(LEVEL_FUNCTIONS[level], record) for record in records] for level in levels}
        for level in levels:
            results = [f.result() for f in futures_per_level[level]]
            output_path = output_dir / f"abstract_level{level}.json"
            hayalab.write_json(str(output_path), results)
            print(f"[OUTPUT] {output_path} ({len(results)} records)", flush=True)


def main() -> None:
    """抽象化を実行する。"""
    args = parse_args()
    pc = PathConfig()

    input_path = args.input or (pc.outputs / "scam" / "approach_minimum" / "cutouts.json")
    output_dir = args.output_dir or (pc.outputs / "scam" / "approach_minimum" / "abstract")
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        raise FileNotFoundError(f"入力ファイルが見つかりません: {input_path}")
    print(f"[INPUT] {input_path}", flush=True)

    records = hayalab.read_json(str(input_path))
    print(f"[RECORDS] {len(records)}", flush=True)

    workers = max(1, args.workers)
    levels: tuple[int, ...] = (0, 1)
    print(f"[WORKERS] {workers} (mb_id 並列)", flush=True)

    if workers <= 1:
        for level in levels:
            output_path = _run_level_sequential(records, level, output_dir)
            print(f"[OUTPUT] {output_path}", flush=True)
        return

    if args.server:
        _run_server(records, levels, output_dir, workers)
        return

    # 入力 cutouts.json が巨大なため、4 レベル分の結果を同時にメモリ保持せず、
    # 1 レベルずつ mb_id 並列で処理して書き出す（ピークメモリを抑制）。
    # ProcessPoolExecutor はレベル間で再利用し、map で入力順（id 昇順）を保つ。
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for level in levels:
            results = list(pool.map(LEVEL_FUNCTIONS[level], records, chunksize=16))
            output_path = output_dir / f"abstract_level{level}.json"
            hayalab.write_json(str(output_path), results)
            print(f"[OUTPUT] {output_path} ({len(results)} records)", flush=True)


if __name__ == "__main__":
    main()
