"""Independent evaluator (Build Spec Section 29, Appendix M).

Scores sealed predictions against qualified truth. The evaluator never
modifies forecasts or the model (Appendix S) and never exposes labels to the
prediction process (SE02).
"""

from .baselines import EmpiricalHazardBaseline, PersistenceBaseline
from .metrics import (
    average_precision,
    brier_scores,
    expected_calibration_error,
    reliability,
)
from .matching import Alert, MatchResult, ObservedEvent, apply_alert_policy, match_events
from .report import (
    EvaluationReport,
    GateStatus,
    evaluate_locked_test,
    episode_block_bootstrap,
)
from .utility import episode_block_bootstrap, primary_utility

__all__ = [
    "EmpiricalHazardBaseline",
    "PersistenceBaseline",
    "average_precision",
    "brier_scores",
    "expected_calibration_error",
    "reliability",
    "Alert",
    "MatchResult",
    "ObservedEvent",
    "apply_alert_policy",
    "EvaluationReport",
    "GateStatus",
    "evaluate_locked_test",
    "episode_block_bootstrap",
    "primary_utility",
]
