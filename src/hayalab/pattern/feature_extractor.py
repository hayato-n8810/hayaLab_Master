"""差分ブロックからの特徴抽出メインモジュール"""

from hayalab.classes.feature import NodePosition, SyntaxFeature
from hayalab.classes.gumtree import ASTNode

from .extractors import (
    DoWhileStatementExtractor,
    ExtractionContext,
    FeatureExtractor,
    ForInStatementExtractor,
    ForStatementExtractor,
    IfStatementExtractor,
    NewExpressionExtractor,
    PropertyIdentifierExtractor,
    WhileStatementExtractor,
)

# デフォルトの抽出器リスト
_DEFAULT_EXTRACTORS: list[FeatureExtractor] = [
    ForStatementExtractor(),
    ForInStatementExtractor(),
    WhileStatementExtractor(),
    DoWhileStatementExtractor(),
    IfStatementExtractor(),
    PropertyIdentifierExtractor(),
    NewExpressionExtractor(),
]


def extract_diff_features(
    diff_block: list[ASTNode],
    extractors: list[FeatureExtractor] | None = None,
) -> SyntaxFeature:
    """差分ブロックから階層構造を保持した特徴を抽出

    Args:
        diff_block: 差分ノードのリスト
        extractors: カスタム抽出器リスト。Noneの場合はデフォルトの抽出器を使用

    Returns:
        SyntaxFeature: 抽出した特徴（ルートノード）
    """
    if extractors is None:
        extractors = _DEFAULT_EXTRACTORS

    root = SyntaxFeature(
        feature_type="diff_root",
        position=NodePosition.ROOT,
        order=0,
    )

    if not diff_block:
        return root

    context = ExtractionContext(nodes=diff_block)
    _extract_recursive(context, root, extractors)

    return root


def _extract_recursive(
    context: ExtractionContext,
    parent_feature: SyntaxFeature,
    extractors: list[FeatureExtractor],
) -> None:
    """再帰的に特徴を抽出

    parent_featureがdiff_rootの場合は全ノードを走査し、
    それ以外の場合は親ノードの[begin, end]範囲内のノードのみを走査する。

    Args:
        context: 抽出コンテキスト
        parent_feature: 親の特徴ノード
        extractors: 使用する抽出器リスト
    """
    order_counter = 0

    # 親ノードの範囲を取得（diff_rootの場合は全範囲）
    parent_begin = parent_feature.begin
    parent_end = parent_feature.end

    for idx in range(len(context.nodes)):
        if idx in context.processed_indices:
            continue

        node = context.nodes[idx]

        # 親ノードの範囲外のノードはスキップ（diff_rootの場合は制限なし）
        if parent_begin is not None and parent_end is not None:
            if node.begin < parent_begin or node.end > parent_end:
                continue

        extracted_feature = None

        # マッチする抽出器を探す
        for extractor in extractors:
            if extractor.matches(node):
                node_context = ExtractionContext(
                    nodes=context.nodes,
                    node_index=idx,
                    order=order_counter,
                    position=_determine_position(context.nodes, idx, parent_feature),
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
                    order=0,
                    position=NodePosition.BODY,
                    processed_indices=context.processed_indices,
                )
                _extract_recursive(child_context, extracted_feature, extractors)

            order_counter += 1


def _determine_position(
    nodes: list[ASTNode],
    node_idx: int,
    parent_feature: SyntaxFeature,
) -> NodePosition:
    """ノードの構造的位置を判定

    祖先チェーンを遡り、制御構造（for/while/if）内での位置を判定する。

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

    paren_based_structures = {
        "while_statement",
        "do_statement",
        "if_statement",
    }

    if parent_type in paren_based_structures:
        return _determine_paren_based_position(nodes, node_idx)

    return NodePosition.BODY


def _determine_paren_based_position(
    nodes: list[ASTNode],
    node_idx: int,
) -> NodePosition:
    """while/do-while/if文内での位置を判定

    祖先チェーンを遡り、parenthesized_expression（条件部）か
    statement_block（本体部）かを判定する。

    Args:
        nodes: ノードリスト
        node_idx: 対象ノードのインデックス

    Returns:
        NodePosition: 構造的位置（CONDITION または BODY）
    """
    target_node = nodes[node_idx]

    for idx in range(node_idx - 1, -1, -1):
        ancestor = nodes[idx]
        if ancestor.begin <= target_node.begin and ancestor.end >= target_node.end:
            if ancestor.name == "parenthesized_expression":
                return NodePosition.CONDITION
            elif ancestor.name == "statement_block":
                return NodePosition.BODY

    return NodePosition.BODY
