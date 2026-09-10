"""Training/evaluator-only target construction (Build Spec Section 11, D.6).

This module is the label boundary: it may read future observations, serving
code may not import it (Appendix C.2, S — ``labels`` is forbidden as a
dependency of serving paths; TR02 guards the split direction).
"""

from .ontology import (
    SIH_TACTICS,
    TASK_DEFINITIONS,
    TASK_IDS,
    TASK_LABEL_TIERS,
    task_label,
)
from .targets import (
    build_clip_targets,
    future_window_targets,
    stage_activity_from_stages,
)

__all__ = [
    "SIH_TACTICS",
    "TASK_DEFINITIONS",
    "TASK_IDS",
    "TASK_LABEL_TIERS",
    "task_label",
    "build_clip_targets",
    "future_window_targets",
    "stage_activity_from_stages",
]
