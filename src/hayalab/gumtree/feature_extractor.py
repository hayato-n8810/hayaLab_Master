"""差分ブロックからの特徴抽出メインモジュール"""

from hayalab.classes.feature import FeatureNode, FeatureTree, NodePosition
from hayalab.classes.gumtree import ASTNode

from .extractors import (
    ExtractionContext,
    FeatureExtractor,
    ForInStatementExtractor,
    ForStatementExtractor,
    IfStatementExtractor,
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
                IfStatementExtractor(),
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

        祖先チェーンを遡り、制御構造（for/while/if）内での位置を判定する。
        - for_statement: 子ノードの順序で判定（0:initializer, 1:condition, 2:update, 3以降:body）
        - while_statement/if_statement: parenthesized_expressionならCONDITION、statement_blockならBODY

        Args:
            nodes: ノードリスト（差分ブロック内）
            node_idx: 対象ノードの差分ブロック内インデックス
            parent_feature: 親の特徴ノード

        Returns:
            NodePosition: 構造的位置
        """
        parent_type = parent_feature.feature_type

        if parent_type == "diff_root":
            return NodePosition.ROOT

        # 制御構造の場合、祖先チェーンから位置を判定
        # control_structures = {
        #     "for_statement",
        # }
        paren_based_structures = {
            "while_statement",
            "if_statement",
        }

        # for文の条件記述部分における位置判定は不完全なので（というより今のところ意味がないので）停止
        # if parent_type in control_structures:
        #     # for文の場合、差分ブロック内の位置関係から判定
        #     return self._determine_for_position(nodes, node_idx, parent_feature)

        if parent_type in paren_based_structures:
            # while/if文の場合、祖先チェーンから判定
            return self._determine_paren_based_position(nodes, node_idx)

        return NodePosition.BODY

    # def _determine_for_position(
    #     self, nodes: list[ASTNode], node_idx: int, parent_feature: FeatureNode
    # ) -> NodePosition:
    #     """for文内での位置を判定

    #     for文の直接の子ノードの順序:
    #     - 0番目: initializer（変数宣言）
    #     - 1番目: condition（条件式）
    #     - 2番目: update（更新式）
    #     - 3番目以降: body（本体）

    #     Args:
    #         nodes: ノードリスト
    #         node_idx: 対象ノードのインデックス
    #         parent_feature: 親の特徴ノード（for文）

    #     Returns:
    #         NodePosition: 構造的位置
    #     """
    #     target_node = nodes[node_idx]

    #     # 親のfor文のインデックスを探す
    #     parent_idx = parent_feature.original_index
    #     if parent_idx is None:
    #         return NodePosition.BODY

    #     parent_node = nodes[parent_idx]
    #     parent_depth = len(parent_node.parent)

    #     # for文の直接の子ノードを収集（深さがparent_depth + 1のノード）
    #     direct_children = []
    #     for idx in range(parent_idx + 1, len(nodes)):
    #         node = nodes[idx]
    #         if len(node.parent) == parent_depth + 1:
    #             # 親のparentを継承しているか確認
    #             if node.parent[:parent_depth] == parent_node.parent:
    #                 direct_children.append((idx, node))

    #     # 対象ノードがfor文の直接の子か、その子孫かを判定
    #     target_depth = len(target_node.parent)

    #     if target_depth == parent_depth + 1:
    #         # 直接の子の場合、順序から判定
    #         for order, (idx, _) in enumerate(direct_children):
    #             if idx == node_idx:
    #                 if order == 0:
    #                     return NodePosition.INITIALIZER
    #                 elif order == 1:
    #                     return NodePosition.CONDITION
    #                 elif order == 2:
    #                     return NodePosition.UPDATE
    #                 else:
    #                     return NodePosition.BODY
    #     else:
    #         # 子孫の場合、祖先チェーンをたどってどの直接の子に属するか判定
    #         for order, (child_idx, child_node) in enumerate(direct_children):
    #             # target_nodeのparentがchild_nodeのパスを含むか確認
    #             child_path = child_node.parent + [child_idx + parent_idx]  # 元ASTのインデックスに変換は不要（差分ブロック内）
    #             # 実際はparent配列を使ってチェック
    #             # target_nodeがchild_nodeの子孫であるかチェック
    #             child_end_pos = child_node.end
    #             if target_node.begin >= child_node.begin and target_node.end <= child_end_pos:
    #                 if order == 0:
    #                     return NodePosition.INITIALIZER
    #                 elif order == 1:
    #                     return NodePosition.CONDITION
    #                 elif order == 2:
    #                     return NodePosition.UPDATE
    #                 else:
    #                     return NodePosition.BODY

    #     return NodePosition.BODY

    def _determine_paren_based_position(self, nodes: list[ASTNode], node_idx: int) -> NodePosition:
        """while/if文内での位置を判定

        祖先チェーンを遡り、parenthesized_expression（条件部）か
        statement_block（本体部）かを判定する。

        Args:
            nodes: ノードリスト
            node_idx: 対象ノードのインデックス

        Returns:
            NodePosition: 構造的位置（CONDITION または BODY）
        """
        target_node = nodes[node_idx]

        # 差分ブロック内で祖先ノードを探す
        # target_nodeのparent配列を使って祖先の名前をチェック
        # ただし差分ブロック内の情報のみで判定する

        # まず、差分ブロック内で対象ノードより前にあり、
        # 対象ノードを包含する範囲のノードを探す
        for idx in range(node_idx - 1, -1, -1):
            ancestor = nodes[idx]
            # 範囲チェック：祖先が対象ノードを包含しているか
            if ancestor.begin <= target_node.begin and ancestor.end >= target_node.end:
                if ancestor.name == "parenthesized_expression":
                    return NodePosition.CONDITION
                elif ancestor.name == "statement_block":
                    return NodePosition.BODY

        return NodePosition.BODY
