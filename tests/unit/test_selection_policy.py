"""v2 selection-policy fitting tests (aggregate budget, exact M.3 semantics).

The policy fit must (a) respect the AGGREGATE false-alert budget across
tasks (the Section-29 gate is aggregate, not per-task), (b) simulate the
evaluator's alert semantics — including post-event records, which can never
match anything and count as false alerts, and (c) abstain a task whose only
operating points exceed the budget rather than publishing a threshold.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from train_profile import fit_selection_policy  # noqa: E402


def _record(task, entity, score, *, cutoff=20, event_bin=None, episode="ep-1"):
    return {
        "task": task,
        "entity": entity,
        "episode": episode,
        "cutoff_window": cutoff,
        "score": score,
        "at_risk": event_bin is None,
        "event": False,
        "event_bin": event_bin,
        "complete_followup": True,
        "asset_hours_weight": 10 * 30 / 3600.0,
    }


class TestAggregateBudget:
    def test_zero_budget_keeps_clean_matches_and_abstains_false_alerts(self):
        # Task 0: a high-score alert that matches a real event (cutoff 20,
        # event at absolute window 30 — strictly after, within the horizon)
        # plus a mid-score record with no event (a false alert if alerted).
        # Task 1: only a no-event record.
        records = [
            _record(0, "host-a", 0.90, event_bin=10),
            _record(0, "host-b", 0.50),
            _record(1, "host-c", 0.80),
        ]
        # asset-hours = 3 entities x 1 cutoff x 300s = 0.25; any budget
        # under 100*1/0.25 = 400 allows 1 FA, so use a tiny budget to
        # force the integer floor to zero unmatched alerts.
        policy = fit_selection_policy(records, budget=1e-6)
        assert "_aggregate" in policy
        # task 0: the (0 FA, 1 matched) point is affordable and optimal
        assert policy["0"]["status"] == "supported"
        assert policy["0"]["warned_events"] == 1
        assert policy["0"]["threshold"] > 0.50  # does not admit host-b
        # task 1: any alert is a false alert; zero budget -> abstain
        assert policy["1"]["threshold"] is None

    def test_aggregate_budget_spends_across_tasks(self):
        # Two tasks whose ONLY alerting points each cost one false alert
        # (their false-alert record scores above the matching one). The
        # aggregate budget allows exactly one false alert in total -> only
        # one task may alert (1 matched), never both.
        records = [
            _record(0, "host-b", 0.95),                            # FA, top score
            _record(0, "host-a", 0.90, event_bin=10),              # matches
            _record(2, "host-d", 0.95),
            _record(2, "host-c", 0.90, event_bin=10),
        ]
        # asset-hours = 4 entities x 1 cutoff x 300s = 1/3 h; budget
        # 300/100ah -> floor(300 * (1/3) / 100) = 1 unmatched alert.
        policy = fit_selection_policy(records, budget=300.0)
        warned = policy["0"].get("warned_events", 0) + policy["2"].get(
            "warned_events", 0
        )
        assert warned == 1
        assert policy["_aggregate"]["calibration_total_warned_events"] == 1
        # the abstaining task publishes no threshold
        assert (policy["0"]["threshold"] is None) ^ (
            policy["2"]["threshold"] is None
        )

    def test_post_event_record_is_a_false_alert_not_free(self):
        # A record AFTER the entity's event (not at risk, event already
        # passed): the evaluator counts its alert as unmatched, so the fit
        # must too. Without it the task is supported at zero budget; with a
        # post-event record scoring above the pre-event one, every alerting
        # point costs a false alert and zero budget forces abstention.
        clean = [_record(3, "host-a", 0.90, event_bin=10, cutoff=20)]
        p_clean = fit_selection_policy(clean, budget=1e-6)
        assert p_clean["3"]["status"] == "supported"
        assert p_clean["3"]["warned_events"] == 1

        with_post = clean + [_record(3, "host-a", 0.95, cutoff=60)]
        p_post = fit_selection_policy(with_post, budget=1e-6)
        assert p_post["3"]["threshold"] is None

    def test_no_events_task_reports_insufficient_support(self):
        records = [_record(4, "host-a", 0.5)]
        policy = fit_selection_policy(records, budget=1.0)
        assert policy["4"]["status"] == "insufficient_positive_support"
        assert policy["4"]["threshold"] is None
