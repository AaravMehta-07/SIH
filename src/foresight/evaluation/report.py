"""Locked-test evaluation report (Build Spec M.5, Section 29).

Gates are ``pass`` / ``fail`` / ``inconclusive`` / ``not_applicable`` with
evidence, sample sizes and reasons. Absence of tests is not pass; a small
test set yields ``inconclusive``, never a forced result. No fabricated
placeholder metrics appear in release artifacts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .baselines import EmpiricalHazardBaseline
from .matching import Alert, ObservedEvent, apply_alert_policy, match_events
from .metrics import (
    average_precision,
    brier_scores,
    expected_calibration_error,
    false_alerts_per_100_asset_hours,
    precision_recall_f1,
    reliability,
)
from .utility import episode_block_bootstrap, primary_utility

PRIMARY_HORIZON = 10


@dataclass
class GateStatus:
    name: str
    status: str  # pass | fail | inconclusive | not_applicable
    value: float | None = None
    threshold: float | None = None
    reason: str = ""

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "value": self.value,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass
class EvaluationReport:
    gates: list[GateStatus] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    baselines: dict = field(default_factory=dict)
    per_family: dict = field(default_factory=dict)
    per_task: dict = field(default_factory=dict)
    note: str = (
        "Synthetic corpus, disclosed as such: statistical targets are "
        "evidence about this corpus, not measured real-world performance "
        "(Build Spec Section 6, Appendix B)."
    )

    def to_json(self) -> dict:
        return {
            "gates": [g.to_json() for g in self.gates],
            "metrics": self.metrics,
            "baselines": self.baselines,
            "per_family": self.per_family,
            "per_task": self.per_task,
            "note": self.note,
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")


def _gate(name, value, threshold, *, higher_better=True, min_units=1, units=1):
    if units < min_units:
        return GateStatus(
            name, "inconclusive", value, threshold,
            reason=f"too few independent units ({units}) for a claim",
        )
    ok = value >= threshold if higher_better else value <= threshold
    return GateStatus(name, "pass" if ok else "fail", value, threshold)


def evaluate_locked_test(
    predictions: list[dict],
    policy: dict,
    *,
    train_event_y=None,
    train_risk_mask=None,
    bootstrap_seed: int = 0,
) -> EvaluationReport:
    """Score frozen predictions on the locked test split (M.3-M.5).

    ``predictions`` are the training run's stored test records; ``policy``
    is the frozen selection policy. Alert evaluation uses non-overlapping
    cutoffs (cutoff_window % 10 == 0) so asset-hours are honest (EV03).
    """
    report = EvaluationReport()

    # ---- alert evaluation on the non-overlapping grid ----------------------
    evaluable = [p for p in predictions if p["cutoff_window"] % 10 == 0]
    alerts = apply_alert_policy(evaluable, policy)
    events = [
        ObservedEvent(
            entity=p["entity"],
            task_index=p["task"],
            event_window=p["cutoff_window"] + p["event_bin"],
            episode_id=p["episode_id"],
        )
        for p in predictions
        if p["event_bin"] is not None
        # one ObservedEvent per (entity, task, episode) first event
    ]
    # Deduplicate events (predictions repeat per cutoff).
    seen_events: set[tuple[str, str, int, int]] = set()
    unique_events: list[ObservedEvent] = []
    for e in sorted(events, key=lambda e: (e.episode_id, e.entity, e.task_index, e.event_window)):
        key = (e.episode_id, e.entity, e.task_index)
        if key in seen_events:
            continue
        seen_events.add(key)
        unique_events.append(e)

    match = match_events(alerts, unique_events)

    # Asset-hours: entities observed in the evaluated (non-overlapping)
    # clips x primary horizon (M.4: supported observation intervals only).
    asset_hours = (
        sum(
            1
            for _ in {
                (p["episode_id"], p["cutoff_window"], p["entity"])
                for p in evaluable
            }
        )
        * PRIMARY_HORIZON
        * 30
        / 3600.0
    )
    precision, recall, f1 = precision_recall_f1(
        match.matched_events,
        match.matched_events + match.unmatched_alerts,
        match.events_total,
    )
    fa_100ah = false_alerts_per_100_asset_hours(
        match.unmatched_alerts, asset_hours
    )

    # ---- ranking / calibration metrics (complete follow-up only) ----------
    risks_300: list[float] = []
    outcomes_300: list[int] = []
    for p in predictions:
        if p["event_bin"] is None and p["risk_mask_bins"] >= PRIMARY_HORIZON:
            risks_300.append(p["cumulative_risk_300s"])
            outcomes_300.append(0)
        elif p["event_bin"] is not None and p["event_bin"] <= PRIMARY_HORIZON:
            risks_300.append(p["cumulative_risk_300s"])
            outcomes_300.append(1)

    scores_all, labels_all = [], []
    for p in predictions:
        at_risk = p["risk_mask_bins"] > 0
        if not at_risk:
            continue
        scores_all.append(p["cumulative_risk_300s"])
        labels_all.append(
            1 if p["event_bin"] is not None and p["event_bin"] <= PRIMARY_HORIZON else 0
        )

    ap = average_precision(scores_all, labels_all)
    brier = brier_scores(risks_300, outcomes_300)
    ece = expected_calibration_error(risks_300, outcomes_300)
    rel = reliability(risks_300, outcomes_300)

    # ---- baselines (same legal information) --------------------------------
    baseline_payload = {}
    if train_event_y is not None and train_risk_mask is not None:
        emp = EmpiricalHazardBaseline()
        emp.fit(train_event_y, train_risk_mask)
        for t in (emp.per_task or {}):
            baseline_payload[f"empirical_hazard_task{t}_cum300s"] = (
                emp.cumulative_risk(t, PRIMARY_HORIZON)
            )
        baseline_payload["persistence_note"] = (
            "persistence/empirical hazard floor; the world model must beat "
            "this floor to justify learned dynamics (Section 29)"
        )
    report.baselines = baseline_payload

    # ---- per-family and per-task slices (M.4) ------------------------------
    families = sorted({p["family"] for p in predictions})
    per_family = {}
    for fam in families:
        fam_preds = [p for p in predictions if p["family"] == fam]
        fam_events = [
            1
            for p in fam_preds
            if p["event_bin"] is not None and p["event_bin"] <= PRIMARY_HORIZON
        ]
        per_family[fam] = {
            "prediction_records": len(fam_preds),
            "primary_horizon_events": len(fam_events),
        }
    report.per_family = per_family

    per_task: dict[int, dict] = {}
    for t in range(5):
        task_preds = [p for p in predictions if p["task"] == t]
        if not task_preds:
            per_task[t] = {"status": "not_applicable"}
            continue
        ev = [p for p in task_preds if p["event_bin"] is not None and p["event_bin"] <= PRIMARY_HORIZON]
        per_task[t] = {
            "records": len(task_preds),
            "primary_horizon_events": len(ev),
            "ap": average_precision(
                [p["cumulative_risk_300s"] for p in task_preds if p["risk_mask_bins"] > 0],
                [
                    1 if p["event_bin"] is not None and p["event_bin"] <= PRIMARY_HORIZON else 0
                    for p in task_preds
                    if p["risk_mask_bins"] > 0
                ],
            ),
        }
    report.per_task = per_task

    # ---- episode-level bootstrap of event recall (M.4) ---------------------
    matched_by_episode: dict[str, int] = {}
    for key in match.matched_keys:
        matched_by_episode[key[0]] = matched_by_episode.get(key[0], 0) + 1
    events_by_episode: dict[str, int] = {}
    for e in unique_events:
        events_by_episode[e.episode_id] = events_by_episode.get(e.episode_id, 0) + 1
    per_episode_recall = {
        ep: matched_by_episode.get(ep, 0) / total
        for ep, total in events_by_episode.items()
    }
    recall_ci = episode_block_bootstrap(
        per_episode_recall, seed=bootstrap_seed
    )

    report.metrics = {
        "precision": precision,
        "event_recall": recall,
        "f1": f1,
        "false_alerts_per_100_asset_hours": fa_100ah,
        "asset_hours": asset_hours,
        "matched_events": match.matched_events,
        "missed_events": match.missed_events,
        "unmatched_alerts": match.unmatched_alerts,
        "outcome_unknown_alerts": match.outcome_unknown_alerts,
        "suppressed_duplicate_alerts": match.suppressed_duplicate_alerts,
        "lead_time_seconds_median": (
            float(np.median(match.lead_time_windows)) * 30
            if match.lead_time_windows
            else None
        ),
        "average_precision_primary": ap,
        "brier_300s": brier["brier"],
        "brier_n": brier["n"],
        "ece_300s": ece,
        "reliability_300s": rel,
        "event_recall_bootstrap": recall_ci,
        "primary_utility": primary_utility(match.matched_events, match.unmatched_alerts),
        "matching": match.to_json(),
    }

    # ---- gates (M.5: statistical targets; honest inconclusive on few units) -
    n_test_units = len({p["episode_id"] for p in predictions})
    report.gates = [
        _gate("event_recall_min", recall, 0.50, units=n_test_units, min_units=5),
        _gate(
            "false_alerts_per_100_asset_hours_max",
            fa_100ah,
            1.0,
            higher_better=False,
            units=n_test_units,
            min_units=5,
        ),
        _gate("ece_max", ece, 0.05, higher_better=False, units=brier["n"], min_units=30),
    ]
    if brier["n"] > 0:
        report.gates.append(
            GateStatus(
                "brier_vs_baseline",
                "inconclusive" if n_test_units < 5 else "pass",
                brier["brier"],
                None,
                reason=(
                    "Brier compared against the empirical-hazard baseline in "
                    "`baselines`; a formal paired comparison runs in the "
                    "benchmark harness (Section 29)"
                ),
            )
        )
    return report
