"""Storage, evaluation and sentinel contract tests (E, M.3, J.1, G.1).

SE01: modified forecast bytes are rejected. SE03: lead time uses the
publication receipt. EV01: repeated alerts cannot inflate recall. NO01: future
residuals cannot influence novelty at a cutoff. ID01: DHCP/NAT ambiguity does
not merge independent histories.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from foresight.contracts.events import EntityRef
from foresight.evaluation.matching import (
    Alert,
    ObservedEvent,
    apply_alert_policy,
    match_events,
)
from foresight.evaluation.metrics import (
    average_precision,
    brier_scores,
    expected_calibration_error,
    false_alerts_per_100_asset_hours,
    precision_recall_f1,
)
from foresight.evaluation.utility import episode_block_bootstrap, primary_utility as primary_util
from foresight.identity.resolver import AddressResolver, IdentityAmbiguity
from foresight.sentinel.scorer import MaturedResidual, SentinelScorer
from foresight.sentinel.reference import NoveltyReference, FEATURE_GROUPS
from foresight.storage.store import Storage

import numpy as np


class TestStorage:
    def test_commit_verify_publish_roundtrip(self, tmp_path: Path):
        storage = Storage(tmp_path / "store")
        record = {
            "id": "fc-test-1",
            "schema": "foresight.core.2026-09",
            "tenant_id": "local",
            "decision_cutoff_ns": "1800000000000",
            "targets": [],
        }
        digest = storage.commit_forecast(record)
        assert len(digest) == 64

        stored = storage.get_forecast("fc-test-1")
        assert stored["id"] == "fc-test-1"
        assert storage.verify_forecast(stored) is True

        # SE01: any modification breaks the hash
        tampered = dict(stored)
        tampered["targets"] = [{"entity_id": "x"}]
        assert storage.verify_forecast(tampered) is False

        # SE03: publication receipt exists and is stable
        first = storage.publish_forecast("fc-test-1")
        second = storage.publish_forecast("fc-test-1")
        assert first == second
        assert storage.publication_receipt("fc-test-1") == first

    def test_tenant_isolation(self, tmp_path: Path):
        storage = Storage(tmp_path / "store")
        storage.commit_forecast(
            {"id": "fc-a", "tenant_id": "tenant-a", "decision_cutoff_ns": "1", "targets": []}
        )
        assert storage.get_forecast("fc-a", tenant_id="tenant-b") is None
        assert storage.get_forecast("fc-a", tenant_id="tenant-a") is not None


class TestEventMatching:
    """M.3 matching rules, EV01 cooldown, EV02 unknown outcomes."""

    def _events(self):
        return [
            ObservedEvent("h1", 2, event_window=30, episode_id="ep1"),
            ObservedEvent("h1", 2, event_window=50, episode_id="ep1"),
        ]

    def test_alert_matches_event_within_horizon(self):
        alerts = [Alert("h1", 2, emission_window=25, score=0.9, episode_id="ep1")]
        result = match_events(alerts, self._events())
        assert result.matched_events == 1
        assert result.lead_time_windows == [5]
        assert result.missed_events == 1

    def test_alert_after_event_does_not_match(self):
        alerts = [Alert("h1", 2, emission_window=31, score=0.9, episode_id="ep1")]
        result = match_events(alerts, self._events())
        assert result.matched_events == 0
        assert result.missed_events == 2

    def test_repeated_alerts_do_not_inflate_recall(self):
        """EV01: ten alerts in cooldown still match at most one event."""
        alerts = [
            Alert("h1", 2, emission_window=25 + i, score=0.9, episode_id="ep1")
            for i in range(10)
        ]
        result = match_events(alerts, self._events())
        assert result.matched_events == 1
        assert result.suppressed_duplicate_alerts == 9

    def test_alert_policy_respects_missing_threshold(self):
        policy = {"2": {"status": "supported", "threshold": 0.5}}
        predictions = [
            {"entity": "h1", "task": 2, "cutoff_window": 25,
             "cumulative_risk_300s": 0.9, "episode_id": "ep1"},
            {"entity": "h1", "task": 3, "cutoff_window": 25,
             "cumulative_risk_300s": 0.99, "episode_id": "ep1"},
        ]
        alerts = apply_alert_policy(predictions, policy)
        assert len(alerts) == 1  # task 3 has no threshold: budget-unreachable


class TestMetrics:
    def test_ap_perfect_and_random(self):
        assert average_precision([0.9, 0.8, 0.1], [1, 1, 0]) == 1.0
        assert average_precision([0.1, 0.9, 0.8], [1, 0, 0]) == pytest.approx(1 / 3)

    def test_precision_recall_f1(self):
        p, r, f1 = precision_recall_f1(matched=4, emitted=5, events=8)
        assert p == pytest.approx(0.8)
        assert r == pytest.approx(0.5)
        assert f1 == pytest.approx(2 * 0.8 * 0.5 / 1.3)

    def test_false_alert_rate_denominator(self):
        assert false_alerts_per_100_asset_hours(2, 200) == pytest.approx(1.0)
        # EV03: zero asset-hours with alerts is infinite, not zero
        assert false_alerts_per_100_asset_hours(1, 0) == float("inf")

    def test_brier_and_ece(self):
        brier = brier_scores([0.0, 1.0], [0, 1])
        assert brier["brier"] == 0.0
        ece = expected_calibration_error([0.2, 0.2, 0.2, 0.2], [0, 0, 1, 1])
        assert ece == pytest.approx(0.3, abs=0.05)

    def test_bootstrap_and_utility(self):
        ci = episode_block_bootstrap({"a": 1.0, "b": 0.0})
        assert ci["units"] == 2
        assert ci["ci_low"] <= ci["mean"] <= ci["ci_high"]
        assert primary_util(5, 1) == 5.0 - 10.0


class TestSentinel:
    def _reference(self) -> NoveltyReference:
        rng = np.random.default_rng(0)
        return NoveltyReference(
            group_residual_median={
                g: np.zeros(len(p)) for g, p in FEATURE_GROUPS.items()
            },
            group_residual_mad={
                g: np.ones(len(p)) for g, p in FEATURE_GROUPS.items()
            },
            embedding_mean=np.zeros(64),
            embedding_scale=np.ones(64),
            fit_episode_count=2,
            fit_residual_count=100,
        )

    def test_no01_future_residuals_rejected(self):
        with pytest.raises(ValueError):
            MaturedResidual(
                entity="h1",
                forecast_cutoff_window=30,
                observed_window=25,  # observed BEFORE the forecast: illegal
                residuals=np.zeros(44),
            )

    def test_reference_like_scoring(self):
        import torch

        scorer = SentinelScorer(self._reference())
        matured = [
            MaturedResidual("h1", 20, 25, np.zeros(44)),
            MaturedResidual("h1", 21, 26, np.zeros(44)),
        ]
        diag = scorer.score(torch.zeros(64), matured, entity="h1")
        assert diag.status == "reference_like"
        assert diag.residual_score == pytest.approx(0.0)
        assert "not an attack probability" in diag.note

    def test_novel_scoring_with_contributing_groups(self):
        import torch

        scorer = SentinelScorer(self._reference())
        residuals = np.zeros(44)
        residuals[10] = 50.0  # destinations group anomaly
        matured = [MaturedResidual("h1", 20, 25, residuals)]
        diag = scorer.score(torch.zeros(64), matured, entity="h1")
        assert diag.status == "novel"
        assert "destinations" in diag.contributing_groups

    def test_unavailable_during_warmup(self):
        import torch

        scorer = SentinelScorer(self._reference())
        diag = scorer.score(torch.zeros(64), [], entity="h1")
        assert diag.status == "unavailable"
        assert diag.residual_score is None


class TestIdentity:
    def test_id01_dhcp_rebinding(self):
        resolver = AddressResolver()
        resolver.bind("10.0.0.5", "laptop-1", valid_from_ns=0, valid_until_ns=1000)
        resolver.bind("10.0.0.5", "laptop-2", valid_from_ns=1000, valid_until_ns=2000)
        assert resolver.resolve("10.0.0.5", 500) == "laptop-1"
        assert resolver.resolve("10.0.0.5", 1500) == "laptop-2"
        # Overlapping conflicting bindings raise in strict mode (NAT/DHCP
        # ambiguity must not silently merge histories, ID01).
        resolver.bind("10.0.0.6", "a", valid_from_ns=0, valid_until_ns=1000)
        resolver.bind("10.0.0.6", "b", valid_from_ns=500, valid_until_ns=1000)
        with pytest.raises(IdentityAmbiguity):
            resolver.resolve("10.0.0.6", 700, strict=True)

    def test_fallback_address_identity(self):
        resolver = AddressResolver()
        assert resolver.resolve("192.168.1.9", 0) == "addr:192.168.1.9"

    def test_entity_ref_validation(self):
        with pytest.raises(Exception):
            EntityRef("t", "bad entity!", "host")
        ok = EntityRef("t", "host-1", "host", link_confidence=0.9)
        assert ok.covers(5)
