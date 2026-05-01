"""ループ構文（for/for-in/for-of/while/do-while）の特徴抽出器"""

from typing import Optional

from hayalab.classes.feature import ASTFragment, LoopFeature, LoopKind
from hayalab.classes.gumtree import ASTNode

from .base import ExtractionContext, FeatureExtractor

# ASTFragment構築時に除外する区切り文字ノード名
_PUNCTUATION_NODES = frozenset({"(", ")", "{", "}", "[", "]", ";", ",", ".", ":"})


def _build_ast_fragment(
    nodes: list[ASTNode],
    root_idx: int,
) -> ASTFragment:
    """指定ノードとその子孫からASTFragmentを再帰的に構築する。

    区切り文字ノードを除外し、コンテキストノード・演算子・リテラル・識別子を保持する。

    Args:
        nodes: 差分ブロック内のノードリスト
        root_idx: ASTFragment化するルートノードのインデックス

    Returns:
        ASTFragment: 構築されたAST部分木
    """
    root_node = nodes[root_idx]
    root_depth = len(root_node.parent)

    # 直接の子ノードのインデックスを収集
    child_indices = []
    for idx in range(root_idx + 1, len(nodes)):
        node = nodes[idx]
        # ルートノードの範囲外に出たら終了
        if node.begin > root_node.end:
            break
        if node.begin < root_node.begin:
            continue
        # 直接の子: depth = root_depth + 1 かつ parent の先頭が一致
        if len(node.parent) == root_depth + 1:
            if node.parent[:root_depth] == root_node.parent:
                child_indices.append(idx)

    # 再帰的にASTFragmentの子を構築（区切り文字を除外）
    children = []
    for child_idx in child_indices:
        child_node = nodes[child_idx]
        if child_node.name in _PUNCTUATION_NODES:
            continue
        children.append(_build_ast_fragment(nodes, child_idx))

    # value: ルートノード名と値が異なる場合のみ設定（例: identifier: "VAR_2", number: "0"）
    # ノード名と値が同じ場合（例: for_statement: for_statement）はvalueを省略
    value = root_node.value if root_node.value != root_node.name else None

    return ASTFragment(
        type=root_node.name,
        value=value,
        children=children,
    )


def _get_descendants_in_range(
    nodes: list[ASTNode],
    parent_idx: int,
) -> list[tuple[int, ASTNode]]:
    """指定ノードの範囲内にある全子孫ノードを取得"""
    parent_node = nodes[parent_idx]
    descendants = []
    for idx in range(parent_idx + 1, len(nodes)):
        node = nodes[idx]
        if node.begin >= parent_node.begin and node.end <= parent_node.end:
            descendants.append((idx, node))
        elif node.begin > parent_node.end:
            break
    return descendants


class ForStatementExtractor(FeatureExtractor):
    """for文の特徴抽出

    for文の直接の子ノードから、( と ) の間にあるノードをヘッダセクションとして識別する:
      - for ( [initialization] [condition] [afterthought] ) body

    ( と ) の間にある named ノード（for, (, ) 自体は除外）を順に:
      [0] → initialization
      [1] → condition
      [2] → afterthought
    """

    def matches(self, node: ASTNode) -> bool:
        return node.name == "for_statement"

    def extract(self, context: ExtractionContext) -> Optional[LoopFeature]:
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # ( と ) の位置を特定して、その間のノードをヘッダセクションとして取得
        paren_open_end = None
        paren_close_begin = None

        for _, child in children:
            if child.name == "(" and paren_open_end is None:
                paren_open_end = child.end
            if child.name == ")":
                paren_close_begin = child.begin

        # ( と ) の間にあるノードをヘッダセクションとして取得
        header_children: list[tuple[int, ASTNode]] = []
        if paren_open_end is not None and paren_close_begin is not None:
            for idx, child in children:
                if child.begin >= paren_open_end and child.end <= paren_close_begin:
                    header_children.append((idx, child))

        # セクション分割: 順序で [0]=init, [1]=condition, [2]=afterthought
        initialization = None
        condition = None
        afterthought = None

        if len(header_children) >= 1:
            initialization = _build_ast_fragment(context.nodes, header_children[0][0])
        if len(header_children) >= 2:
            condition = _build_ast_fragment(context.nodes, header_children[1][0])
        if len(header_children) >= 3:
            afterthought = _build_ast_fragment(context.nodes, header_children[2][0])

        return LoopFeature(
            feature_type="for_statement",
            loop_kind=LoopKind.FOR,
            position=context.position,
            order=context.order,
            initialization=initialization,
            condition=condition,
            afterthought=afterthought,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )


class ForInStatementExtractor(FeatureExtractor):
    """for-in/for-of文の特徴抽出

    for_in_statementの直接の子ノードから:
      - "of" ノードがあれば FOR_OF、なければ FOR_IN
      - in/of の直後のノードを iterable_source としてASTFragment化
    """

    def matches(self, node: ASTNode) -> bool:
        return node.name == "for_in_statement"

    def extract(self, context: ExtractionContext) -> Optional[LoopFeature]:
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        # in/of キーワードの検出と iterable_source の取得
        has_of = False
        iterable_source = None
        found_operator = False

        for idx, child in children:
            if child.name == "of":
                has_of = True
                found_operator = True
                continue
            if child.name == "in":
                found_operator = True
                continue
            # in/of の直後のノード（)より前）を iterable_source とする
            if found_operator and child.name != ")":
                iterable_source = _build_ast_fragment(context.nodes, idx)
                break

        loop_kind = LoopKind.FOR_OF if has_of else LoopKind.FOR_IN
        feature_type = "for_of_statement" if has_of else "for_in_statement"

        return LoopFeature(
            feature_type=feature_type,
            loop_kind=loop_kind,
            position=context.position,
            order=context.order,
            iterable_source=iterable_source,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )


class WhileStatementExtractor(FeatureExtractor):
    """while文の特徴抽出

    parenthesized_expression の内容をASTFragment化して condition に格納する。
    """

    def matches(self, node: ASTNode) -> bool:
        return node.name == "while_statement"

    def extract(self, context: ExtractionContext) -> Optional[LoopFeature]:
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        condition = self._extract_condition(context, children)

        return LoopFeature(
            feature_type="while_statement",
            loop_kind=LoopKind.WHILE,
            position=context.position,
            order=context.order,
            condition=condition,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )

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


class DoWhileStatementExtractor(FeatureExtractor):
    """do-while文の特徴抽出

    do { body } while ( condition ) の構造。
    parenthesized_expression の内容をASTFragment化して condition に格納する。
    """

    def matches(self, node: ASTNode) -> bool:
        return node.name == "do_statement"

    def extract(self, context: ExtractionContext) -> Optional[LoopFeature]:
        node = context.get_node()
        children = self._get_children_nodes(context, context.node_index)

        condition = self._extract_condition(context, children)

        return LoopFeature(
            feature_type="do_statement",
            loop_kind=LoopKind.DO_WHILE,
            position=context.position,
            order=context.order,
            condition=condition,
            original_index=context.node_index,
            begin=node.begin,
            end=node.end,
        )

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
