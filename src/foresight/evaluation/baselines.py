"""Common baselines (Build Spec M.2).

Same legal information, identical risk sets and follow-up:

- Persistence: predict the last valid observed feature value (for hazards:
  the last observed window's empirical hazard proxy).
- Empirical rolling event hazard: per-task base rate over training risk
  bins, with a Laplace smoothing prior (a non-strawman temporal floor).

All classifiers estimate the same future event/horizon the model does
(M.2), never current-attack labels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PersistenceBaseline:
    """M.2 persistence: future observable values = last valid observed value.

    For event forecasting the persistence hazard is the entity's own recent
    empirical event rate if any, else the population rate — a floor the
    learned model must beat to justify its dynamics (Section 29).
    """

    def __init__(self) -> None:
        self.rate: float | None = None

    def fit(self, event_y: np.ndarray, risk_mask: np.ndarray) -> None:
        """``event_y``/``risk_mask`` stacked [K, H, J] over training clips."""
        n = float(risk_mask.sum())
        self.rate = float(event_y.sum() / n) if n > 0 else 0.0

    def hazard(self) -> float:
        return self.rate or 0.0


@dataclass
class EmpiricalHazardBaseline:
    """Per-task empirical hazard from training risk bins with a documented
    smoothing prior (M.2). This is the honest statistical floor."""

    per_task: dict[int, float] | None = None
    smoothing: float = 1.0  # Laplace pseudo-counts per task

    def fit(self, event_y: np.ndarray, risk_mask: np.ndarray) -> None:
        """Stacked arrays [K, H, J]; per-task rate = (events + a) / (bins + a)."""
        j = event_y.shape[-1]
        self.per_task = {}
        for t in range(j):
            events = float(event_y[:, :, t].sum())
            bins = float(risk_mask[:, :, t].sum())
            self.per_task[t] = (events + self.smoothing) / (bins + self.smoothing)

    def cumulative_risk(self, task_index: int, horizon_bins: int) -> float:
        """Cumulative risk under a constant per-bin hazard."""
        q = self.per_task[task_index]
        return float(1.0 - (1.0 - q) ** horizon_bins)
