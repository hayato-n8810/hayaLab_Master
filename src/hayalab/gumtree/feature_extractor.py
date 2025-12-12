"""差分ブロックからの特徴抽出メインモジュール"""

from hayalab.classes.feature import FeatureNode, FeatureTree, NodePosition
from hayalab.classes.gumtree import ASTNode

from .extractors import (
    ExtractionContext,
    FeatureExtractor,
    ForInStatementExtractor,
    ForStatementExtractor,
    NewExpressionExtractor,
    PropertyIdentifierExtractor,
    WhileStatementExtractor,
)


class DiffFeatureExtractor:
    """差分ブロックからの特徴抽出メインクラス"""

    def __init__(self, extractors: list[FeatureExtractor] | None = None):
        """利用可能な抽出器を登録

        Args:
            extractors: カスタム抽出器リスト。Noneの場合はデフォルトの抽出器を使用
        """
        if extractors is not None:
            self.extractors = extractors
        else:
            self.extractors: list[FeatureExtractor] = [
                ForStatementExtractor(),
                ForInStatementExtractor(),
                WhileStatementExtractor(),
                PropertyIdentifierExtractor(),
                NewExpressionExtractor(),
            ]

    def add_extractor(self, extractor: FeatureExtractor) -> None:
        """抽出器を追加

        Args:
            extractor: 追加する抽出器
        """
        self.extractors.append(extractor)

    def extract_features(self, diff_block: dict) -> FeatureTree:
        """差分ブロックから階層構造を保持した特徴を抽出

        Args:
            diff_block: 差分ブロックとそのアクションの辞書
                形式: {"action": str, "diff_block": list[ASTNode]}

        Returns:
            FeatureTree: 特徴ツリー
        """
        root = FeatureNode(
            feature_type="diff_root",
            position=NodePosition.ROOT,
            depth=0,
            order=0,
        )

        action = diff_block["action"]
        block = diff_block["diff_block"]

        if not block:
            return FeatureTree(action=action, root=root)

        context = ExtractionContext(nodes=block)
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
