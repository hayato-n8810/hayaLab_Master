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


class FeatureNode(BaseModel):
    """抽出された特徴ノード"""

    feature_type: str  # ノードの種類 (for_statement, call_expression, etc.)
    position: NodePosition = NodePosition.ROOT  # 構造的位置
    depth: int = 0  # 階層の深さ
    order: int = 0  # 同一階層内での実行順序
    value: Optional[str] = None  # 識別子名など
    children: list["FeatureNode"] = []

    # 元のASTノード情報（デバッグ・トレース用）
    original_index: Optional[int] = None
    begin: Optional[int] = None
    end: Optional[int] = None

    def to_dict(self) -> dict:
        """辞書形式に変換（JSON出力用）"""
        result = {
            "type": self.feature_type,
            "position": self.position.value,
            "depth": self.depth,
            "order": self.order,
        }
        if self.value is not None:
            result["value"] = self.value
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result


class FeatureTree(BaseModel):
    """特徴ツリー（差分ブロック全体の特徴）"""

    action: str  # アクション名 (delete-tree, update-node, etc.)
    root: FeatureNode  # ルートノード

    def to_dict(self) -> dict:
        """辞書形式に変換（JSON出力用）"""
        return {
            "action": self.action,
            "features": self.root.to_dict() if self.root.children else {},
        }
