"""特徴抽出器の実装モジュール"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from hayalab.classes.feature import FeatureNode, FeatureTree, NodePosition
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
    """特徴抽出の基底クラス"""

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


class ForStatementExtractor(FeatureExtractor):
    """for文の特徴抽出"""

    def matches(self, node: ASTNode) -> bool:
        """for文にマッチするか判定"""
        return node.name == "for_statement"

    def extract(self, context: ExtractionContext) -> Optional[FeatureNode]:
        """for文から特徴を抽出"""
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # 子ノードにbinary_expressionがあるか確認
        has_binary = any(child.name == "binary_expression" for _, child in children)
        feature_type = "for_statement_binary_expression" if has_binary else "for_statement"

        return FeatureNode(
            feature_type=feature_type,
            position=context.position,
            depth=context.depth,
            order=context.order,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )


class ForInStatementExtractor(FeatureExtractor):
    """for-in/for-of文の特徴抽出"""

    def matches(self, node: ASTNode) -> bool:
        """for-in文にマッチするか判定"""
        return node.name == "for_in_statement"

    def extract(self, context: ExtractionContext) -> Optional[FeatureNode]:
        """for-in/for-of文から特徴を抽出"""
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # 子ノードに"of"があるか確認
        has_of = any(child.name == "of" for _, child in children)
        feature_type = "for_of_statement" if has_of else "for_in_statement"

        return FeatureNode(
            feature_type=feature_type,
            position=context.position,
            depth=context.depth,
            order=context.order,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )


class WhileStatementExtractor(FeatureExtractor):
    """while文の特徴抽出"""

    def matches(self, node: ASTNode) -> bool:
        """while文にマッチするか判定"""
        return node.name == "while_statement"

    def extract(self, context: ExtractionContext) -> Optional[FeatureNode]:
        """while文から特徴を抽出"""
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # 子ノードにbinary_expressionがあるか確認
        has_binary = any(child.name == "binary_expression" for _, child in children)
        feature_type = "while_statement_binary_expression" if has_binary else "while_statement"

        return FeatureNode(
            feature_type=feature_type,
            position=context.position,
            depth=context.depth,
            order=context.order,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )


class PropertyIdentifierExtractor(FeatureExtractor):
    """メソッド呼び出し（property_identifier）の特徴抽出"""

    def matches(self, node: ASTNode) -> bool:
        """property_identifierにマッチするか判定"""
        return node.name == "property_identifier"

    def extract(self, context: ExtractionContext) -> Optional[FeatureNode]:
        """メソッド呼び出しから特徴を抽出"""
        node = context.get_node()

        return FeatureNode(
            feature_type="call_exp",
            position=context.position,
            depth=context.depth,
            order=context.order,
            value=node.value,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )


class NewExpressionExtractor(FeatureExtractor):
    """new式（コンストラクタ呼び出し）の特徴抽出"""

    def matches(self, node: ASTNode) -> bool:
        """new_expressionにマッチするか判定"""
        return node.name == "new_expression"

    def extract(self, context: ExtractionContext) -> Optional[FeatureNode]:
        """new式から特徴を抽出"""
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # 子ノードからidentifier（コンストラクタの名前）を探す
        constructor_name = None
        for _, child in children:
            if child.name == "identifier":
                constructor_name = child.value
                break

        return FeatureNode(
            feature_type="new_exp",
            position=context.position,
            depth=context.depth,
            order=context.order,
            value=constructor_name,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )


class DiffFeatureExtractor:
    """差分ブロックからの特徴抽出メインクラス"""

    def __init__(self):
        """利用可能な抽出器を登録"""
        self.extractors: list[FeatureExtractor] = [
            ForStatementExtractor(),
            ForInStatementExtractor(),
            WhileStatementExtractor(),
            PropertyIdentifierExtractor(),
            NewExpressionExtractor(),
        ]

    def extract_features(self, diff_block: list[ASTNode], action: str) -> FeatureTree:
        """差分ブロックから階層構造を保持した特徴を抽出

        Args:
            diff_block: 差分ブロックのノードリスト
            action: アクション名

        Returns:
            FeatureTree: 特徴ツリー
        """
        root = FeatureNode(
            feature_type="diff_root",
            position=NodePosition.ROOT,
            depth=0,
            order=0,
        )

        if not diff_block:
            return FeatureTree(action=action, root=root)

        context = ExtractionContext(nodes=diff_block)
        self._extract_recursive(context, root)

        return FeatureTree(action=action, root=root)

    def _extract_recursive(self, context: ExtractionContext, parent_feature: FeatureNode) -> None:
        """再帰的に特徴を抽出

        Args:
            context: 抽出コンテキスト
            parent_feature: 親の特徴ノード
        """
        order_counter = 0

        for idx in range(len(context.nodes)):
            if idx in context.processed_indices:
                continue

            node = context.nodes[idx]
            extracted_feature = None

            # マッチする抽出器を探す
            for extractor in self.extractors:
                if extractor.matches(node):
                    node_context = ExtractionContext(
                        nodes=context.nodes,
                        node_index=idx,
                        depth=parent_feature.depth + 1,
                        order=order_counter,
                        position=self._determine_position(context.nodes, idx, parent_feature),
                        processed_indices=context.processed_indices,
                    )
                    extracted_feature = extractor.extract(node_context)
                    break

            if extracted_feature:
                context.processed_indices.add(idx)
                parent_feature.children.append(extracted_feature)

                # 子ノードを再帰的に処理
                child_indices = context.get_children_indices(idx)
                if child_indices:
                    child_context = ExtractionContext(
                        nodes=context.nodes,
                        node_index=idx,
                        depth=extracted_feature.depth,
                        order=0,
                        position=NodePosition.BODY,
                        processed_indices=context.processed_indices,
                    )
                    self._extract_recursive(child_context, extracted_feature)

                order_counter += 1

    def _determine_position(self, nodes: list[ASTNode], node_idx: int, parent_feature: FeatureNode) -> NodePosition:
        """ノードの構造的位置を判定

        Args:
            nodes: ノードリスト
            node_idx: 対象ノードのインデックス
            parent_feature: 親の特徴ノード

        Returns:
            NodePosition: 構造的位置
        """
        # 親の特徴タイプに基づいて位置を判定
        parent_type = parent_feature.feature_type

        if parent_type == "diff_root":
            return NodePosition.ROOT

        # 制御構造の場合、子の位置を判定
        # TODO: より詳細な位置判定（条件部/本体部の区別など）
        if parent_type in (
            "for_statement",
            "for_statement_binary_expression",
            "for_in_statement",
            "for_of_statement",
            "while_statement",
            "while_statement_binary_expression",
        ):
            return NodePosition.BODY

        return NodePosition.BODY
