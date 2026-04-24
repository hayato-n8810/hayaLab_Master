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
        """for文から特徴を抽出

        条件部の特徴をヒューリスティックに探索:
        - expression_statementを探し、その子孫にproperty_identifierがあるか
        - 直接の子にbinary_expressionがあるか
        """
        node = context.get_node()
        # children = self._get_children_nodes(context, context.node_index)

        # 条件の特徴はひとまず考慮しないこととする(2025/12/15)
        # 条件部の特徴を探索
        # has_binary = self._analyze_condition_part(context, children)

        return FeatureNode(
            feature_type="for_statement",
            position=context.position,
            depth=context.depth,
            order=context.order,
            # has_binary_expression=has_binary,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )

    # def _analyze_condition_part(
    #     self, context: ExtractionContext, children: list[tuple[int, ASTNode]]
    # ) -> tuple[bool, bool]:
    #     """for文の条件部を解析

    #     for文の構造: for ( initializer ; condition ; update ) body
    #     条件部はexpression_statementとして現れる（2番目の直接の子）

    #     Args:
    #         context: 抽出コンテキスト
    #         children: 直接の子ノードリスト

    #     Returns:
    #         bool: has_binary_expression
    #     """
    #     has_binary = False

    #     # expression_statementを探す（for文の条件部）
    #     for idx, child in children:
    #         if child.name == "expression_statement":
    #             # expression_statementの子孫を探索
    #             descendants = self._get_descendants(context, idx)
    #             for _, desc in descendants:
    #                 if desc.name == "binary_expression":
    #                     has_binary = True
    #             break  # 最初のexpression_statementのみ処理

    #     # 直接の子にbinary_expressionがあるかも確認
    #     if not has_binary:
    #         has_binary = any(child.name == "binary_expression" for _, child in children)

    #     return has_binary

    # def _get_descendants(
    #     self, context: ExtractionContext, parent_idx: int
    # ) -> list[tuple[int, ASTNode]]:
    #     """指定ノードの全子孫を取得"""
    #     parent_node = context.nodes[parent_idx]
    #     descendants = []

    #     for idx in range(parent_idx + 1, len(context.nodes)):
    #         node = context.nodes[idx]
    #         # 範囲チェック：親の範囲内にあるか
    #         if node.begin >= parent_node.begin and node.end <= parent_node.end:
    #             descendants.append((idx, node))
    #         elif node.begin > parent_node.end:
    #             break  # 親の範囲を超えたら終了

    #     return descendants


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
        """while文から特徴を抽出

        条件部の特徴をヒューリスティックに探索:
        - parenthesized_expressionを探し、その子孫にproperty_identifierがあるか
        - 条件部にbinary_expressionがあるか
        """
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # 条件部の特徴を探索
        has_binary = self._analyze_condition_part(context, children)

        return FeatureNode(
            feature_type="while_statement",
            position=context.position,
            depth=context.depth,
            order=context.order,
            has_binary_expression=has_binary,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )

    def _analyze_condition_part(self, context: ExtractionContext, children: list[tuple[int, ASTNode]]) -> tuple[bool, bool]:
        """while文の条件部を解析

        while文の構造: while ( condition ) body
        条件部はparenthesized_expressionとして現れる

        Args:
            context: 抽出コンテキスト
            children: 直接の子ノードリスト

        Returns:
            bool: has_binary_expression
        """
        has_binary = False

        # parenthesized_expressionを探す（while文の条件部）
        for idx, child in children:
            if child.name == "parenthesized_expression":
                # parenthesized_expressionの子孫を探索
                descendants = self._get_descendants(context, idx)
                for _, desc in descendants:
                    if desc.name == "binary_expression":
                        has_binary = True
                break  # 最初のparenthesized_expressionのみ処理

        return has_binary

    def _get_descendants(self, context: ExtractionContext, parent_idx: int) -> list[tuple[int, ASTNode]]:
        """指定ノードの全子孫を取得"""
        parent_node = context.nodes[parent_idx]
        descendants = []

        for idx in range(parent_idx + 1, len(context.nodes)):
            node = context.nodes[idx]
            # 範囲チェック：親の範囲内にあるか
            if node.begin >= parent_node.begin and node.end <= parent_node.end:
                descendants.append((idx, node))
            elif node.begin > parent_node.end:
                break  # 親の範囲を超えたら終了

        return descendants


class IfStatementExtractor(FeatureExtractor):
    """if文（if_statement）の特徴抽出"""

    def matches(self, node: ASTNode) -> bool:
        """if_statementにマッチするか判定"""
        return node.name == "if_statement"

    def extract(self, context: ExtractionContext) -> Optional[FeatureNode]:
        """if文から特徴を抽出

        条件部の特徴をヒューリスティックに探索:
        - parenthesized_expressionを探し、その子孫にproperty_identifierがあるか
        - 条件部にbinary_expressionがあるか
        """
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # 条件部の特徴を探索
        has_binary = self._analyze_condition_part(context, children)

        return FeatureNode(
            feature_type="if_statement",
            position=context.position,
            depth=context.depth,
            order=context.order,
            has_binary_expression=has_binary,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )

    def _analyze_condition_part(self, context: ExtractionContext, children: list[tuple[int, ASTNode]]) -> tuple[bool, bool]:
        """if文の条件部を解析

        if文の構造: if ( condition ) body [else ...]
        条件部はparenthesized_expressionとして現れる

        Args:
            context: 抽出コンテキスト
            children: 直接の子ノードリスト

        Returns:
            bool: has_binary_expression
        """
        has_binary = False

        # parenthesized_expressionを探す（if文の条件部）
        for idx, child in children:
            if child.name == "parenthesized_expression":
                # parenthesized_expressionの子孫を探索
                descendants = self._get_descendants(context, idx)
                for _, desc in descendants:
                    if desc.name == "binary_expression":
                        has_binary = True
                break  # 最初のparenthesized_expressionのみ処理

        return has_binary

    def _get_descendants(self, context: ExtractionContext, parent_idx: int) -> list[tuple[int, ASTNode]]:
        """指定ノードの全子孫を取得"""
        parent_node = context.nodes[parent_idx]
        descendants = []

        for idx in range(parent_idx + 1, len(context.nodes)):
            node = context.nodes[idx]
            # 範囲チェック：親の範囲内にあるか
            if node.begin >= parent_node.begin and node.end <= parent_node.end:
                descendants.append((idx, node))
            elif node.begin > parent_node.end:
                break  # 親の範囲を超えたら終了

        return descendants
