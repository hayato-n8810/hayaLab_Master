"""パターン統合モジュール"""

from .abstraction import abstract_cutout, compute_signature
from .aggregate import aggregate_equivalence_classes
from .aggregation_observation import compute_abstraction_observations

# 新規パイプライン（pattern-extraction-pipeline-design）
from .cutout import cut_diff, cut_diff_all_depths
from .detect import compute_detection, detect
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
    # extract_diff_features,
)
from .scoring import compute_rho, compute_sigma, compute_size_score
from .select import select_optimal_depth

__all__ = [
    "integrate_features",
    # "extract_diff_features",
    "ExtractionContext",
    "FeatureExtractor",
    "ForInStatementExtractor",
    "ForStatementExtractor",
    "IfStatementExtractor",
    "NewExpressionExtractor",
    "PropertyIdentifierExtractor",
    "WhileStatementExtractor",
    "DoWhileStatementExtractor",
    # Pipeline
    "cut_diff",
    "cut_diff_all_depths",
    "abstract_cutout",
    "compute_signature",
    "detect",
    "compute_detection",
    "aggregate_equivalence_classes",
    "compute_abstraction_observations",
    "compute_rho",
    "compute_sigma",
    "compute_size_score",
    "select_optimal_depth",
]
