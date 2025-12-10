"""GumtreeのASTと差分情報を表す型定義モジュール"""

from typing import List, Optional, Tuple

from pydantic import BaseModel, model_validator


class ASTNode(BaseModel):
    """gumtreeASTノード"""

    begin: int
    end: int
    label: str
    name: str
    value: str
    parent: List[int]


class AST(BaseModel):
    """元コードとAST"""

    code: str
    tree: List[ASTNode]  # 自動的にASTNode型のリストとしてパースされる


class Ancestor(BaseModel):
    """祖先ノード"""

    index: int  # 祖先ノードの元のASTにおけるインデックス
    name: str  # 祖先ノード名前

    @model_validator(mode="before")
    @classmethod
    def list_to_dict(cls, data: list) -> dict:
        """リスト形式 [index, name] が来たら辞書に変換

        Args:
            data (list): [index, name]形式のリスト

        Returns:
            dict: dictオブジェクト

        Raises:
            ValueError: データがリスト形式でない場合
        """
        # データが辞書形式の場合はそのまま返す
        if isinstance(data, dict):
            return data
        # データがリスト形式の場合は辞書に変換
        if isinstance(data, list):
            return {"index": data[0], "name": data[1]}
        # それ以外の場合はエラー
        raise ValueError(f"Expected list or dict format, got {type(data).__name__}")


class GumAction(BaseModel):
    """gumtree diffのアクション情報"""

    action: str  # アクション名 (update-node, insert-tree, delete-tree, move-tree)
    tree: str  # 対象ノード
    index: int = None  # 差分ノードの元のASTにおけるインデックス
    ancestors: List[Ancestor] = None  # 差分ノードの祖先リスト
    label: Optional[str] = None  # (update-node の場合の新しいnode)
    at: Optional[int] = None  # (insert-node の場合の挿入位置)


class GumDiff(BaseModel):
    """gumtree diffの差分解析結果"""

    matches: List[Tuple[int, int]]  # マッチしたノードペアのリスト (base_index, head_index)
    base_ast: AST  # 元コードのAST
    base_actions: List[GumAction]  # 変更前のASTにある差分アクション
    head_ast: AST  # 変更後コードのAST
    head_actions: List[GumAction]  # 変更後のASTにある差分アクション


"""
GumtreeDiff(
    matches = [(0,0), (1,1), ...],
    base_ast = AST(
        code = "",
        tree = [
            ASTNode(begin=0, end=282, label='program [0,282]', name='program', value='program', parent=[]),
            ...
        ]
    ),
    base_actions = [
        GumtreeAction(name='update', index=5, ancestors=[Ancestor(index=2, name='function_declaration'), ...]),
        ...
    ],
    head_ast = AST(
        code = "",
        tree = [
            ASTNode(begin=0, end=282, label='program [0,282]', name='program', value='program', parent=[]),
            ...
        ]
    ),
    head_actions = [
        GumtreeAction(name='update', index=5, ancestors=[Ancestor(index=2, name='function_declaration'), ...]),
        ...
    ]
)
"""

# 利用例（メソッドを書く必要すらありません）
# data = json.load(f)
# diff = GumtreeDiff.model_validate(data)
