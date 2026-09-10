"""Utility weights and episode-block bootstrap (Build Spec M.4, M.5).

The utility is defined in ``evaluation.yaml`` before final evaluation:
``matched_event_reward * warned_events - false_alert_cost * false_alerts``
with a predeclared sensitivity grid. Bootstrap resamples episode units for
both models in paired comparisons — never correlated windows (M.4).
"""

from __future__ import annotations

import numpy as np


def primary_utility(
    warned_events: int,
    false_alerts: int,
    *,
    matched_event_reward: float = 1.0,
    false_alert_cost: float = 10.0,
) -> float:
    """Dimensionless primary utility (M.5 implementation default)."""
    return matched_event_reward * warned_events - false_alert_cost * false_alerts


def episode_block_bootstrap(
    per_episode_values: dict[str, float],
    *,
    statistic=np.mean,
    replicates: int = 2000,
    seed: int = 0,
) -> dict:
    """Bootstrap over episode units (M.4). Returns mean, 2.5/97.5 percentiles."""
    names = sorted(per_episode_values)
    if not names:
        return {"mean": None, "ci_low": None, "ci_high": None, "units": 0}
    values = np.array([per_episode_values[n] for n in names], dtype=np.float64)
    rng = np.random.default_rng(seed)
    stats = np.empty(replicates)
    for r in range(replicates):
        sample = values[rng.integers(0, len(values), size=len(values))]
        stats[r] = statistic(sample)
    return {
        "mean": float(statistic(values)),
        "ci_low": float(np.percentile(stats, 2.5)),
        "ci_high": float(np.percentile(stats, 97.5)),
        "units": len(names),
    }
