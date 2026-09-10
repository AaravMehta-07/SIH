"""Metric implementations (Build Spec M.4).

Precision/recall/F1/FPR with explicit denominators, false alerts per 100
observed asset-hours, Brier by horizon, reliability with disclosed bins,
ECE. Every function is deterministic and unit-testable against hand
computations (M.5 hard gate: hand-computed metric agreement).
"""

from __future__ import annotations

import numpy as np


def average_precision(scores: list[float], labels: list[int]) -> float:
    if not labels or sum(labels) == 0:
        return 0.0
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    hits, ap, prev_recall = 0, 0.0, 0.0
    total = sum(labels)
    for rank, i in enumerate(order, start=1):
        if labels[i]:
            hits += 1
            recall = hits / total
            precision = hits / rank
            ap += precision * (recall - prev_recall)
            prev_recall = recall
    return ap


def precision_recall_f1(
    matched: int, emitted: int, events: int
) -> tuple[float, float, float]:
    """Precision = matched / evaluable emitted alerts; event recall =
    warned qualified events / all qualified observed events (M.4)."""
    precision = matched / emitted if emitted else 0.0
    recall = matched / events if events else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return precision, recall, f1


def false_alerts_per_100_asset_hours(
    false_alerts: int, asset_hours: float
) -> float:
    """M.4: 100 x unmatched evaluable alerts / observation-supported
    asset-hours. The denominator is published alongside, never assumed."""
    if asset_hours <= 0:
        return float("inf") if false_alerts else 0.0
    return 100.0 * false_alerts / asset_hours


def brier_scores(
    risks: list[float], outcomes: list[int]
) -> dict[str, float]:
    """Mean squared error of cumulative risk against occurrence by the
    horizon (complete-follow-up strata only, M.4)."""
    if not risks:
        return {"brier": 0.0, "n": 0}
    risks_arr = np.asarray(risks, dtype=np.float64)
    out_arr = np.asarray(outcomes, dtype=np.float64)
    return {
        "brier": float(np.mean((risks_arr - out_arr) ** 2)),
        "n": len(risks),
    }


def reliability(
    risks: list[float], outcomes: list[int], bins: int = 10
) -> dict:
    """Reliability diagram data with disclosed bin edges and counts (M.4)."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    risks_arr = np.asarray(risks)
    out_arr = np.asarray(outcomes, dtype=np.float64)
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        mask = (risks_arr > lo) & (risks_arr <= hi) if b > 0 else (
            (risks_arr >= lo) & (risks_arr <= hi)
        )
        count = int(mask.sum())
        rows.append(
            {
                "bin_lower": float(lo),
                "bin_upper": float(hi),
                "count": count,
                "mean_forecast": float(risks_arr[mask].mean()) if count else None,
                "observed_rate": float(out_arr[mask].mean()) if count else None,
            }
        )
    return {"bins": rows, "bin_count": bins}


def expected_calibration_error(
    risks: list[float], outcomes: list[int], bins: int = 10
) -> float:
    """ECE with disclosed bin count (M.4: ECE alone does not certify
    probability correctness — it is reported with the reliability table)."""
    if not risks:
        return 0.0
    rel = reliability(risks, outcomes, bins)
    total = sum(row["count"] for row in rel["bins"])
    if total == 0:
        return 0.0
    ece = 0.0
    for row in rel["bins"]:
        if row["count"] == 0:
            continue
        ece += (
            row["count"]
            / total
            * abs(row["mean_forecast"] - row["observed_rate"])
        )
    return float(ece)
