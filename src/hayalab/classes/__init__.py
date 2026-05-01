"""データクラス定義モジュール"""

from .feature import ASTFragment, LoopFeature, LoopKind, NodePosition, SyntaxFeature
from .gumtree import AST, ASTNode, GumAction, GumDiff, ActionBlock
from .codeql import Sarif

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
    # codeql
    "Sarif",
]