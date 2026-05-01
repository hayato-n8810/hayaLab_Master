"""特徴抽出のための型定義モジュール"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class NodePosition(str, Enum):
    """ノードがどの構造的位置にあるか"""

    ROOT = "root"  # トップレベル
    CONDITION = "condition"  # 条件式の中 (if, for, while の条件部)
    BODY = "body"  # 本体ブロックの中
    INITIALIZER = "initializer"  # for文の初期化部
    UPDATE = "update"  # for文の更新部
    ARGUMENT = "argument"  # 関数呼び出しの引数
    CALLEE = "callee"  # 呼び出し対象


class ASTFragment(BaseModel):
    """AST部分木の簡易表現（セクション内容の中間表現）

    コンテキストノード（declaration, expression等）、演算子、リテラル、識別子を
    木構造で保持する。純粋な区切り文字（括弧、セミコロン等）は除外される。
    """

    type: str  # ノード型名
    value: Optional[str] = None  # 値（identifierの名前、演算子、リテラル値）
    children: list["ASTFragment"] = []

    def to_dict(self) -> dict:
        """辞書形式に変換（JSON出力用）"""
        result = {"type": self.type}
        if self.value is not None:
            result["value"] = self.value
        if self.children:
            result["children"] = [c.to_dict() for c in self.children]
        return result


class SyntaxFeature(BaseModel):
    """抽出された構文要素の基底クラス

    階層はJSONのネスト構造（children）で表現
    """

    feature_type: str  # ノードの種類 (for_statement, call_expression, etc.)
    position: NodePosition = NodePosition.ROOT  # 構造的位置
    order: int = 0  # 同一階層内での実行順序
    value: Optional[str] = None  # 識別子名など
    children: list["SyntaxFeature"] = []

    # 元のASTノード情報（デバッグ・トレース用、to_dictには含めない）
    original_index: Optional[int] = None
    begin: Optional[int] = None
    end: Optional[int] = None

    def to_dict(self) -> dict:
        """辞書形式に変換（JSON出力用）"""
        result = {
            "type": self.feature_type,
            "position": self.position.value,
            "order": self.order,
        }
        if self.value is not None:
            result["value"] = self.value
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result


class LoopKind(str, Enum):
    """ループの種別"""

    FOR = "for"  # for (init; cond; update)
    FOR_IN = "for_in"  # for (x in obj)
    FOR_OF = "for_of"  # for (x of iterable)
    WHILE = "while"  # while (cond)
    DO_WHILE = "do_while"  # do { } while (cond)


class LoopFeature(SyntaxFeature):
    """ループ構文の中間表現

    各セクションの内容はASTFragment（ネストJSON木構造）で表現する。
    コンテキストノード・演算子・リテラル・識別子を保持し、
    区切り文字（括弧、セミコロン等）は除外される。
    """

    loop_kind: LoopKind

    # for文: ;区切りの各セクション
    initialization: Optional[ASTFragment] = None
    condition: Optional[ASTFragment] = None  # while/do-whileでも使用
    afterthought: Optional[ASTFragment] = None

    # for-in/for-of: イテラブル源
    iterable_source: Optional[ASTFragment] = None

    def to_dict(self) -> dict:
        """辞書形式に変換（JSON出力用）"""
        result = super().to_dict()
        result["loop_kind"] = self.loop_kind.value
        if self.initialization is not None:
            result["initialization"] = self.initialization.to_dict()
        if self.condition is not None:
            result["condition"] = self.condition.to_dict()
        if self.afterthought is not None:
            result["afterthought"] = self.afterthought.to_dict()
        if self.iterable_source is not None:
            result["iterable_source"] = self.iterable_source.to_dict()
        return result
