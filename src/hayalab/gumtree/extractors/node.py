"""gumtreeにおけるノード（特徴）抽出器"""

from typing import Optional

from hayalab.classes.feature import FeatureNode
from hayalab.classes.gumtree import ASTNode

from .base import ExtractionContext, FeatureExtractor


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
