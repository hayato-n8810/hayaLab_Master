"""gumtreeにおけるノード（特徴）抽出器

ループ系以外の構文要素の特徴抽出を行う。
ループ系（for, for-in, while, do-while）は loop.py に移動。
"""

from typing import Optional

from hayalab.classes.feature import ASTFragment, SyntaxFeature
from hayalab.classes.gumtree import ASTNode

from .base import ExtractionContext, FeatureExtractor
from .loop import _build_ast_fragment


class PropertyIdentifierExtractor(FeatureExtractor):
    """メソッド呼び出し（property_identifier）の特徴抽出"""

    def matches(self, node: ASTNode) -> bool:
        """property_identifierにマッチするか判定"""
        return node.name == "property_identifier"

    def extract(self, context: ExtractionContext) -> Optional[SyntaxFeature]:
        """メソッド呼び出しから特徴を抽出"""
        node = context.get_node()

        return SyntaxFeature(
            feature_type="call_exp",
            position=context.position,
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

    def extract(self, context: ExtractionContext) -> Optional[SyntaxFeature]:
        """new式から特徴を抽出"""
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # 子ノードからidentifier（コンストラクタの名前）を探す
        constructor_name = None
        for _, child in children:
            if child.name == "identifier":
                constructor_name = child.value
                break

        return SyntaxFeature(
            feature_type="new_exp",
            position=context.position,
            order=context.order,
            value=constructor_name,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )


class IfStatementExtractor(FeatureExtractor):
    """if文（if_statement）の特徴抽出

    条件部（parenthesized_expression）の内容をASTFragmentとして抽出する。
    """

    def matches(self, node: ASTNode) -> bool:
        """if_statementにマッチするか判定"""
        return node.name == "if_statement"

    def extract(self, context: ExtractionContext) -> Optional[SyntaxFeature]:
        """if文から特徴を抽出"""
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # 条件部のASTFragmentを抽出
        condition = self._extract_condition(context, children)

        feature = SyntaxFeature(
            feature_type="if_statement",
            position=context.position,
            order=context.order,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )

        # TODO: conditionをSyntaxFeatureに統合する方法を検討
        # 現時点ではif文のconditionは子ノードの再帰処理に委ねる

        return feature

    def _extract_condition(
        self,
        context: ExtractionContext,
        children: list[tuple[int, ASTNode]],
    ) -> Optional[ASTFragment]:
        """parenthesized_expressionの内容をASTFragment化"""
        for idx, child in children:
            if child.name == "parenthesized_expression":
                return _build_ast_fragment(context.nodes, idx)
        return None
