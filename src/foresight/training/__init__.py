"""Training package (Build Spec Section 15, Appendices I.1-I.2, D.6, C.2).

Public surface:
- :class:`ClipTargets` — the D.6 per-clip target tensor contract that the
  labels module must produce.
- :func:`assert_trainable_split` — the TR02 test-split guard.
- Loss functions and the combined Section-15 objective.
- :class:`Trainer` / :class:`CurriculumSchedule` — the I.1 training loop.
"""

from .losses import (
    LossBreakdown,
    LossWeights,
    compute_clip_loss,
    masked_bce,
    masked_gaussian_nll,
    masked_multilabel_bce,
    masked_survival_nll,
    observable_nll,
    per_bin_survival_nll,
)
from .targets import (
    ALL_SPLITS,
    NON_TRAINABLE_SPLITS,
    TRAINABLE_SPLITS,
    ClipTargets,
    assert_trainable_split,
)
from .trainer import (
    DEFAULT_SAMPLING_POLICY,
    CurriculumSchedule,
    StepLog,
    Trainer,
    set_seed,
)

__all__ = [
    "ALL_SPLITS",
    "NON_TRAINABLE_SPLITS",
    "TRAINABLE_SPLITS",
    "ClipTargets",
    "LossBreakdown",
    "LossWeights",
    "CurriculumSchedule",
    "StepLog",
    "Trainer",
    "assert_trainable_split",
    "compute_clip_loss",
    "masked_bce",
    "masked_gaussian_nll",
    "masked_multilabel_bce",
    "masked_survival_nll",
    "observable_nll",
    "per_bin_survival_nll",
    "set_seed",
    "DEFAULT_SAMPLING_POLICY",
]
