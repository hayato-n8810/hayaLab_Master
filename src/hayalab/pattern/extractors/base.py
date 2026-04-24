"""特徴抽出の基底クラスとコンテキスト"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from hayalab.classes.feature import FeatureNode, NodePosition
from hayalab.classes.gumtree import ASTNode


@dataclass
class ExtractionContext:
    """抽出時のコンテキスト情報"""

    nodes: list[ASTNode]  # 差分ブロックのノードリスト
    node_index: int = 0  # 現在処理中のノードインデックス
    depth: int = 0  # 階層の深さ
    order: int = 0  # 同一階層内での順序
    position: NodePosition = NodePosition.ROOT  # 構造的位置
    processed_indices: set[int] = field(default_factory=set)  # 処理済みインデックス

    def get_node(self) -> ASTNode:
        """現在のノードを取得"""
        return self.nodes[self.node_index]

    def get_children_indices(self, parent_idx: int) -> list[int]:
        """指定したノードの直接の子ノードのインデックスを取得"""
        parent_node = self.nodes[parent_idx]
        parent_depth = len(parent_node.parent)
        target_depth = parent_depth + 1

        # 親ノードのparentに自身のインデックスを加えたものが子のparentになる
        # ただし差分ブロック内でのインデックスではなく、元ASTのインデックスを使用
        children_indices = []

        for idx in range(parent_idx + 1, len(self.nodes)):
            node = self.nodes[idx]
            if len(node.parent) == target_depth:
                # 親のparentが子のparentの先頭部分と一致するか確認
                if node.parent[:parent_depth] == parent_node.parent:
                    children_indices.append(idx)

        return children_indices

    def child_context(self, child_idx: int, position: NodePosition, order: int) -> "ExtractionContext":
        """子ノード用のコンテキストを作成"""
        return ExtractionContext(
            nodes=self.nodes,
            node_index=child_idx,
            depth=self.depth + 1,
            order=order,
            position=position,
            processed_indices=self.processed_indices,
        )


class FeatureExtractor(ABC):
    """特徴抽出の基底(抽象)クラス"""

    @abstractmethod
    def matches(self, node: ASTNode) -> bool:
        """このExtractorが処理すべきノードか判定"""
        pass

    @abstractmethod
    def extract(self, context: ExtractionContext) -> Optional[FeatureNode]:
        """特徴を抽出"""
        pass

    def _get_children_nodes(self, context: ExtractionContext, parent_idx: int) -> list[tuple[int, ASTNode]]:
        """子ノードとそのインデックスのリストを取得"""
        indices = context.get_children_indices(parent_idx)
        return [(idx, context.nodes[idx]) for idx in indices]
