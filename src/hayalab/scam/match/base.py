"""低速パターン matcher の基底クラスと PatternMatch データモデル。"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol

from hayalab.classes.gumtree import ASTNode


@dataclass(frozen=True)
class PatternMatch:
    """1 件のパターンマッチ結果。

    Attributes:
        mb_id: MBDiff レコードの id。
        side: 検出サイド（当面は "base" のみ）。
        pattern_id: パターン番号（1〜10）。
        confidence: マッチの信頼度。
        node_index: 起点ノードのインデックス。
        begin: ソース上の開始バイト位置。
        end: ソース上の終了バイト位置。
        snippet: code[begin:end]（先頭 200 文字でクリップ）。
        diff_linked: Stage B の diff 連動判定結果。
        diff_reason: diff_linked=True の場合の判定理由（省略可）。
    """

    mb_id: int
    side: Literal["base", "head"]
    pattern_id: int
    confidence: Literal["high", "medium", "low"]
    node_index: int
    begin: int
    end: int
    snippet: str
    diff_linked: bool = False
    diff_reason: str | None = None


def make_pattern_match(
    nodes: list[ASTNode],
    idx: int,
    code: str,
    *,
    mb_id: int,
    pattern_id: int,
    confidence: Literal["high", "medium", "low"],
    side: Literal["base", "head"] = "base",
    snippet_limit: int = 200,
) -> PatternMatch:
    """``nodes[idx]`` の begin/end/snippet を抽出して PatternMatch を生成する。

    各 matcher の ``find()`` 末尾で共通する snippet 切り出し処理を集約するヘルパー。

    Args:
        nodes: ASTNode のリスト。
        idx: 起点ノードのインデックス。
        code: ソースコード文字列（``begin:end`` で snippet を切る）。
        mb_id: MBDiff レコードの id。
        pattern_id: パターン番号（1〜10）。
        confidence: マッチの信頼度。
        side: 検出サイド（``"base"`` / ``"head"``）。
        snippet_limit: snippet の最大文字数（既定 200）。

    Returns:
        生成された PatternMatch。``diff_linked`` は False、``diff_reason`` は None。
    """
    begin = nodes[idx].begin
    end = nodes[idx].end
    return PatternMatch(
        mb_id=mb_id,
        side=side,
        pattern_id=pattern_id,
        confidence=confidence,
        node_index=idx,
        begin=begin,
        end=end,
        snippet=code[begin:end][:snippet_limit],
    )


class SlowPatternMatcher(Protocol):
    """低速パターン matcher のプロトコル。

    各 matcher はこのインターフェースを実装する。
    """

    pattern_id: int
    pattern_name: str

    def find(self, nodes: list[ASTNode], code: str, mb_id: int = 0) -> Iterator[PatternMatch]:
        """Nodes から低速パターンを検出して PatternMatch を yield する。

        Args:
            nodes: base_ast.tree の ASTNode リスト。
            code: base_ast.code の文字列。
            mb_id: MBDiff レコードの id（デフォルト 0）。

        Yields:
            検出した PatternMatch。
        """
        ...
