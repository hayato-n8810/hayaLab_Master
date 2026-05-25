"""パターン統合モジュール"""

from .abstraction import abstract_cutout, compute_signature

from .integrate import integrate_features
from .others import (
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


__all__ = [
    # Feature extractors
    "integrate_features",
    "ExtractionContext",
    "FeatureExtractor",
    "ForInStatementExtractor",
    "ForStatementExtractor",
    "IfStatementExtractor",
    "NewExpressionExtractor",
    "PropertyIdentifierExtractor",
    "WhileStatementExtractor",
    "DoWhileStatementExtractor",
    # Pattern pipeline
    "abstract_cutout",
    "compute_signature",
    "detect",
    "compute_detection",
    "aggregate_equivalence_classes",
    "compute_abstraction_observations"
]
