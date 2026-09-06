"""データクラス定義モジュール"""

from .codeql import Sarif
from .feature import ASTFragment, LoopFeature, LoopKind, NodePosition, SyntaxFeature
from .gumtree import AST, ActionBlock, ASTNode, GumAction, GumDiff, TreeContext, TreeMatch, TreePattern

__all__ = [
    # Feature
    "SyntaxFeature",
    "LoopFeature",
    "LoopKind",
    "ASTFragment",
    "NodePosition",
    # GumTree
    "AST",
    "ASTNode",
    "GumAction",
    "GumDiff",
    "ActionBlock",
    "TreePattern",
    "TreeContext",
    "TreeMatch",
    # codeql
    "Sarif",
]
