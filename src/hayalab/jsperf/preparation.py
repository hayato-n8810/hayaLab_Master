"""preparation_html を扱う純粋関数群。

BeautifulSoup による寛容パースで、インライン `<script>` 抽出・外部 `<script src>`
抽出・インライン `<script>` 除去・DOM 要素残存判定・4 カテゴリ分類を提供する。
"""

from __future__ import annotations

from typing import Literal

from bs4 import BeautifulSoup

_PARSER: str = "html.parser"
_WRAPPER_TAGS: frozenset[str] = frozenset({"html", "head", "body", "[document]"})

PreparationCategory = Literal["empty", "inline_only", "external_only", "with_dom"]


def _parse(html: str) -> BeautifulSoup:
    """HTML フラグメントを BeautifulSoup オブジェクトに変換する。

    Args:
        html: 生 HTML 文字列。

    Returns:
        BeautifulSoup: パース結果。
    """
    return BeautifulSoup(html or "", _PARSER)


def extract_inline_scripts(html: str) -> list[str]:
    """インライン `<script>`（`src` 属性を持たないもの）の中身を DOM 順に返す。

    Args:
        html: preparation_html の生文字列。

    Returns:
        list[str]: インライン `<script>` の中身のリスト（DOM 出現順）。
    """
    soup = _parse(html)
    scripts: list[str] = []
    for tag in soup.find_all("script"):
        if tag.has_attr("src"):
            continue
        scripts.append(tag.decode_contents())
    return scripts


def extract_external_script_srcs(html: str) -> list[str]:
    """外部 `<script src="...">` の URL を DOM 順に返す。

    ユニーク化は呼び出し側の責務。空文字の src は除外する。

    Args:
        html: preparation_html の生文字列。

    Returns:
        list[str]: `src` 属性の値のリスト（DOM 出現順）。
    """
    soup = _parse(html)
    srcs: list[str] = []
    for tag in soup.find_all("script"):
        src = tag.get("src")
        if isinstance(src, str) and src.strip():
            srcs.append(src.strip())
    return srcs


def strip_inline_scripts(html: str) -> str:
    """インライン `<script>` タグだけを除去した HTML を返す。

    外部 `<script src>` と DOM 要素は残す。

    Args:
        html: preparation_html の生文字列。

    Returns:
        str: インライン `<script>` を除いた HTML 文字列。
    """
    soup = _parse(html)
    for tag in soup.find_all("script"):
        if not tag.has_attr("src"):
            tag.decompose()
    return str(soup)


def has_dom_elements(html: str) -> bool:
    """HTML に `<script>` 以外の DOM 要素が含まれるか判定する。

    Args:
        html: 判定対象の HTML 文字列。

    Returns:
        bool: `<script>` 以外のタグが 1 つでもあれば True。
    """
    soup = _parse(html)
    for tag in soup.find_all(True):
        if tag.name in _WRAPPER_TAGS:
            continue
        if tag.name == "script":
            continue
        return True
    return False


def classify_preparation_html(html: str) -> PreparationCategory:
    """preparation_html を 4 カテゴリに分類する。

    Args:
        html: preparation_html の生文字列。

    Returns:
        PreparationCategory: 以下のいずれか。

            - ``"empty"``: 空文字または空白のみ。
            - ``"inline_only"``: インライン `<script>` のみ（除去後、外部
              `<script src>` も DOM 要素も残らない）。
            - ``"external_only"``: 除去後、外部 `<script src>` のみが残る。
            - ``"with_dom"``: 除去後、`<script>` 以外の DOM 要素が残る。
    """
    if not (html or "").strip():
        return "empty"

    stripped = strip_inline_scripts(html)
    if has_dom_elements(stripped):
        return "with_dom"
    if extract_external_script_srcs(stripped):
        return "external_only"
    return "inline_only"
