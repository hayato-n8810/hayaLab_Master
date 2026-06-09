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
