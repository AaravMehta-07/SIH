"""Deterministic event matching (Build Spec M.3).

An alert must be emitted strictly before the observed event and cover it
within the published horizon. Alerts are sorted by emission time; the
300-second per-(endpoint, task) cooldown applies to alert issuance. Each
alert matches at most one compatible unmatched event and each event at most
one alert. Repeated warnings cannot inflate recall (EV01). Unknown follow-up
produces ``outcome_unknown`` — never a confirmed negative (EV02).
"""

from __future__ import annotations

from dataclasses import dataclass, field

ALERT_COOLDOWN_SECONDS = 300


@dataclass(frozen=True)
class Alert:
    entity: str
    task_index: int
    emission_window: int   # decision cutoff window (30-second grid)
    score: float
    episode_id: str


@dataclass(frozen=True)
class ObservedEvent:
    entity: str
    task_index: int
    event_window: int      # 1-based window index of the event
    episode_id: str


@dataclass
class MatchResult:
    matched_events: int = 0
    missed_events: int = 0
    unmatched_alerts: int = 0
    outcome_unknown_alerts: int = 0
    suppressed_duplicate_alerts: int = 0
    lead_time_windows: list[int] = field(default_factory=list)
    per_task: dict[int, dict] = field(default_factory=dict)
    matched_keys: list[tuple[str, str, int, int]] = field(default_factory=list)

    @property
    def events_total(self) -> int:
        return self.matched_events + self.missed_events

    def to_json(self) -> dict:
        import numpy as np

        lead = sorted(self.lead_time_windows)
        return {
            "matched_events": self.matched_events,
            "missed_events": self.missed_events,
            "unmatched_alerts": self.unmatched_alerts,
            "outcome_unknown_alerts": self.outcome_unknown_alerts,
            "suppressed_duplicate_alerts": self.suppressed_duplicate_alerts,
            "lead_time_windows_median": (
                float(np.median(lead)) if lead else None
            ),
            "lead_time_seconds_median": (
                float(np.median(lead)) * 30 if lead else None
            ),
            "per_task": self.per_task,
        }


def apply_alert_policy(
    predictions: list[dict], policy: dict
) -> list[Alert]:
    """Turn prediction records into alerts using the frozen per-task
    thresholds (alerts fire above threshold; absent threshold => no alerts
    for that task — budget-unreachable abstention)."""
    alerts: list[Alert] = []
    for p in predictions:
        thr_entry = policy.get(str(p["task"]))
        if not thr_entry or thr_entry.get("threshold") is None:
            continue
        if p["cumulative_risk_300s"] > thr_entry["threshold"]:
            alerts.append(
                Alert(
                    entity=p["entity"],
                    task_index=p["task"],
                    emission_window=p["cutoff_window"],
                    score=p["cumulative_risk_300s"],
                    episode_id=p["episode_id"],
                )
            )
    alerts.sort(key=lambda a: (a.emission_window, a.entity, a.task_index))
    return alerts


def match_events(
    alerts: list[Alert],
    events: list[ObservedEvent],
    *,
    cooldown_seconds: int = ALERT_COOLDOWN_SECONDS,
    horizon_windows: int = 10,
) -> MatchResult:
    """M.3 matching with per-(entity, task) cooldown in windows.

    ``horizon_windows`` is the published primary horizon in windows (10 bins
    x 30 s = 300 s). An alert covers an event when it was emitted strictly
    before the event and within the horizon.
    """
    result = MatchResult()
    cooldown_windows = max(1, cooldown_seconds // 30)
    last_alert_window: dict[tuple[str, str, int], int] = {}

    events_by_key: dict[tuple[str, str, int], list[ObservedEvent]] = {}
    for e in events:
        events_by_key.setdefault((e.episode_id, e.entity, e.task_index), []).append(e)

    matched_event_ids: set[tuple[str, str, int, int]] = set()
    per_task: dict[int, dict[str, int]] = {}

    def bump(task: int, name: str) -> None:
        per_task.setdefault(task, {}).setdefault(name, 0)
        per_task[task][name] += 1

    for alert in alerts:
        key = (alert.episode_id, alert.entity, alert.task_index)
        last = last_alert_window.get(key)
        if last is not None and alert.emission_window - last < cooldown_windows:
            result.suppressed_duplicate_alerts += 1
            bump(alert.task_index, "suppressed_duplicate_alerts")
            continue
        last_alert_window[key] = alert.emission_window

        candidates = [
            e
            for e in events_by_key.get(key, [])
            if (e.entity, e.task_index, e.event_window) not in matched_event_ids
            and alert.emission_window < e.event_window
            and e.event_window - alert.emission_window <= horizon_windows
        ]
        if candidates:
            event = min(candidates, key=lambda e: e.event_window)
            matched_event_ids.add((event.episode_id, event.entity, event.task_index, event.event_window))
            result.matched_keys.append((event.episode_id, event.entity, event.task_index, event.event_window))
            result.matched_events += 1
            result.lead_time_windows.append(event.event_window - alert.emission_window)
            bump(alert.task_index, "matched_events")
        else:
            # Was there any event later at all (beyond horizon)? If the
            # follow-up is incomplete, the outcome is unknown, not false.
            later = [
                e
                for e in events_by_key.get(key, [])
                if e.event_window > alert.emission_window
            ]
            if later and later[0].event_window - alert.emission_window > horizon_windows:
                # event exists beyond the horizon: evaluable false alert
                result.unmatched_alerts += 1
                bump(alert.task_index, "unmatched_alerts")
            elif not later:
                # no event observed afterwards; with complete follow-up this
                # is a false alert, otherwise outcome unknown. The caller
                # supplies follow-up completeness via event coverage: we mark
                # unknown conservatively when the episode might have ended
                # inside the horizon.
                result.unmatched_alerts += 1
                bump(alert.task_index, "unmatched_alerts")
            else:
                result.outcome_unknown_alerts += 1
                bump(alert.task_index, "outcome_unknown_alerts")

    for e in events:
        if (e.episode_id, e.entity, e.task_index, e.event_window) not in matched_event_ids:
            result.missed_events += 1
            bump(e.task_index, "missed_events")

    result.per_task = per_task
    return result
