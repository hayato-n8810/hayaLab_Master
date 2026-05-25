"""データクラス定義モジュール"""

from .codeql import Sarif
from .feature import ASTFragment, LoopFeature, LoopKind, NodePosition, SyntaxFeature
from .gumtree import AST, ActionBlock, ASTNode, GumAction, GumDiff
from .pattern import (
    AbstractionObservation,
    ClassMember,
    EquivalenceClass,
    IdentifierSlot,
    Pattern,
    SelectionResult,
)

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
    # Pattern pipeline
    "Pattern",
    "ClassMember",
    "EquivalenceClass",
    "SelectionResult",
    "AbstractionObservation",
    "IdentifierSlot",
]
