"""SENTINEL novelty diagnostics (Build Spec Section 17, Appendix J).

Publishes **unexpectedness, not attack probability** (A09). Two streams:

- Residual novelty: a past forecast's predicted observables versus the
  observations that actually arrived. Only matured residuals from earlier
  forecasts are available at a cutoff (NO01) — the scorer refuses future
  residuals by construction.
- Embedding distance: entity-memory distance from a frozen benign
  reference. A score derived from the same encoder is correlated evidence,
  not an independent sensor (Section 17) — it is labeled as such.

Thresholds are chosen at a fixed benign-change false-novelty budget on
development data (J.1). Benign novelty is change detection only; it is never
mapped to maliciousness.
"""

from .reference import (
    FEATURE_GROUPS,
    NoveltyReference,
    fit_novelty_reference,
)
from .scorer import (
    MaturedResidual,
    NoveltyDiagnostics,
    SentinelScorer,
    collect_matured_residuals,
)

__all__ = [
    "FEATURE_GROUPS",
    "NoveltyReference",
    "fit_novelty_reference",
    "MaturedResidual",
    "NoveltyDiagnostics",
    "SentinelScorer",
    "collect_matured_residuals",
]
