"""scam の slot 方式抽象化 公開 API (L1: identifier, L2: + リテラル)。

paper (SCAM2026) の確定方針: 抽象化 (Type-2 段階) × 類似度 (τ) の 2 軸で粒度制御。
メイン分析は L1 / L2 の 2 段階のみ。

Levels:
    L1 (Skeleton):  identifier 値 (VAR_*/FUNCTION_*) を ``$v*`` / ``$f*`` に slot 化。
    L2 (Standard):  L1 + literal 値 (number / string_fragment) を ``$n*`` / ``$s*`` に
                    slot 化。 さらに ``regex`` ノード配下を ``$r*`` に置換。
"""

from __future__ import annotations

from typing import Any

from .node import abstract_record


def abstract_level1(record: dict[str, Any]) -> dict[str, Any]:
    """L1 (Skeleton): identifier 値のみを cutout 内で slot 化する。

    前処理で割り当てられた ``VAR_*`` / ``FUNCTION_*`` を cutout 内で一貫した
    ``$v0`` / ``$f0`` 形式の slot ID に再採番する。 リテラル・API 名・演算子・
    非終端は全て保持する。

    Args:
        record: 1 mb_id 分の cutout 集合 (``{"id", "cutouts"}``)。

    Returns:
        L1 抽象化済みレコード。
    """
    return abstract_record(record, 1)


def abstract_level2(record: dict[str, Any]) -> dict[str, Any]:
    """L2 (Standard): L1 + リテラル値の slot 化（regex 子孫含む）。

    ``number`` / ``string_fragment`` ノードの値を ``$n0`` / ``$s0`` 形式の
    slot ID に置換する。さらに ``regex`` ノードの ``origin_index`` を
    ``parent`` に含む全ノード（regex 子孫）の値を ``$r0`` 形式の slot ID に
    置換する。 regex 子孫は**削除せず slot 化**する方針。

    Args:
        record: 1 mb_id 分の cutout 集合 (``{"id", "cutouts"}``)。

    Returns:
        L2 抽象化済みレコード。
    """
    return abstract_record(record, 2)
