"""Tier B action tests: policy, Section-23 state machine, paired trials."""

from __future__ import annotations

import pytest

from foresight.actions import (
    ACTION_POLICY,
    ActionStateMachine,
    IllegalTransitionError,
    check_policy,
    new_proposal,
    paired_trial,
    sign_approval,
)
from foresight.data.episodes import build_episode

_NS = 1_000_000_000
OBSERVED = [
    ("ws-41.corp.local", "ext-c2-01.net"),
    ("ext-c2-01.net", "ws-41.corp.local"),
    ("web-01.dmz.local", "ext-attacker-01.net"),
]


def _proposal(**overrides):
    kwargs = dict(
        source="ws-41.corp.local",
        target="ext-c2-01.net",
        forecast_id="fc-1",
        forecast_hash="abc123",
        cutoff_window=35,
        session_id="sess-1",
        now_ns=1_000_000_000_000,
    )
    kwargs.update(overrides)
    return new_proposal(**kwargs)


# ---------------------------------------------------------------------------
# Policy checks
# ---------------------------------------------------------------------------

def test_policy_allows_observed_external_pair() -> None:
    failures = check_policy(
        action_type="block_edge",
        source="ws-41.corp.local",
        target="ext-c2-01.net",
        forecast_id="fc-1",
        forecast_hash="abc",
        observed_pairs=OBSERVED,
    )
    assert failures == []


def test_policy_rejects_unobserved_and_internal_pairs() -> None:
    unobserved = check_policy(
        action_type="block_edge",
        source="ws-11.corp.local",
        target="ext-c2-01.net",
        forecast_id="fc-1",
        forecast_hash="abc",
        observed_pairs=OBSERVED,
    )
    assert any("not observed" in f for f in unobserved)

    internal = check_policy(
        action_type="block_edge",
        source="ws-41.corp.local",
        target="file-01.corp.local",
        forecast_id="fc-1",
        forecast_hash="abc",
        observed_pairs=[("ws-41.corp.local", "file-01.corp.local")],
    )
    assert any("internal<->external" in f for f in internal)

    unbound = check_policy(
        action_type="block_edge",
        source="ws-41.corp.local",
        target="ext-c2-01.net",
        forecast_id="",
        forecast_hash="",
        observed_pairs=OBSERVED,
    )
    assert any("forecast hash" in f for f in unbound)


# ---------------------------------------------------------------------------
# Approval + state machine
# ---------------------------------------------------------------------------

def test_approval_signature_binds_proposal() -> None:
    proposal = _proposal()
    sig = sign_approval(proposal)
    machine = ActionStateMachine(proposal, now_ns=1_000_000_000_000)
    machine.authorize(sig)
    assert machine.status == "authorized"
    # a signature for a DIFFERENT proposal must not authorize
    other = _proposal(source="web-01.dmz.local", target="ext-attacker-01.net")
    with pytest.raises(IllegalTransitionError, match="signature mismatch"):
        ActionStateMachine(other, now_ns=1_000_000_000_000).authorize(sig)


def test_state_machine_happy_path() -> None:
    proposal = _proposal()
    machine = ActionStateMachine(proposal, now_ns=1_000_000_000_000)
    machine.authorize(sign_approval(proposal))
    machine.begin_execution()
    machine.complete("succeeded", {"trial": "ok"})
    assert machine.status == "succeeded"
    assert machine.outcome == {"trial": "ok"}
    # terminal: no further transitions
    with pytest.raises(IllegalTransitionError):
        machine.begin_execution()


def test_execution_requires_authorization() -> None:
    machine = ActionStateMachine(_proposal(), now_ns=1_000_000_000_000)
    with pytest.raises(IllegalTransitionError, match="authorization required"):
        machine.begin_execution()
    assert machine.status == "proposed"


def test_execute_once_idempotency() -> None:
    proposal = _proposal()
    machine = ActionStateMachine(proposal, now_ns=1_000_000_000_000)
    machine.authorize(sign_approval(proposal))
    machine.begin_execution()
    with pytest.raises(IllegalTransitionError, match="idempotency"):
        machine.begin_execution()


def test_expired_never_executes() -> None:
    proposal = _proposal(now_ns=0)  # expires at 600s; "now" is long past
    machine = ActionStateMachine(proposal, now_ns=1_000_000_000_000)
    assert machine.reconcile() == "expired"
    with pytest.raises(IllegalTransitionError):
        machine.authorize(sign_approval(proposal))


def test_audit_log_records_transitions() -> None:
    proposal = _proposal()
    machine = ActionStateMachine(proposal, now_ns=1_000_000_000_000)
    machine.authorize(sign_approval(proposal))
    machine.begin_execution()
    machine.complete("succeeded", {})
    states = [entry["to"] for entry in machine.audit]
    assert states == ["proposed", "authorized", "executing", "succeeded"]


def test_unknown_recovers() -> None:
    proposal = _proposal()
    machine = ActionStateMachine(proposal, now_ns=1_000_000_000_000)
    machine.authorize(sign_approval(proposal))
    machine.begin_execution()
    machine.complete("unknown", {"reason": "connector timeout"})
    assert machine.reconcile() == "recovered"


# ---------------------------------------------------------------------------
# Paired range trials (Section 22)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def c2_episode():
    return build_episode("c2-exfil", 0, seed=7000)


def _post_c2_cutoff(episode) -> int:
    """A cutoff strictly after the first C2 chain step but before the
    lateral step (so the causal suppression has something to avert)."""
    c2 = next(s for s in episode.chain if s.task_index == 3)
    lateral = next(
        (s for s in episode.chain if s.task_index == 2 and s.time_ns > c2.time_ns),
        None,
    )
    assert lateral is not None, "c2-exfil must script post-C2 lateral movement"
    after_c2 = c2.time_ns // (30 * _NS) + 1
    before_lateral = lateral.time_ns // (30 * _NS)
    return max(20, min(after_c2, before_lateral - 1, 80))


def test_paired_trial_averts_downstream_lateral(c2_episode) -> None:
    cutoff = _post_c2_cutoff(c2_episode)
    result = paired_trial(
        c2_episode, cutoff,
        source="ws-41.corp.local", target="ext-c2-01.net",
    )
    payload = result.to_json()
    assert payload["postcondition_verified"] is True
    # no-action arm keeps the scripted post-cutoff events
    assert payload["no_action"]["events"], "the campaign continues unblocked"
    # the action arm averts the ws-41 lateral movement (lost C2)
    averted_pairs = {
        (e["source"], e["target"]) for e in payload["averted_events"]
    }
    assert ("ws-41.corp.local", "file-01.corp.local") in averted_pairs
    action_sources = {e["source"] for e in payload["action_arm"]["events"]}
    assert "ws-41.corp.local" not in action_sources
    # the block bit something
    assert payload["action_arm"]["packets_blocked"] > 0


def test_paired_trial_prefix_is_paired(c2_episode) -> None:
    """Same seed, same prefix: both arms share the episode start."""
    cutoff = _post_c2_cutoff(c2_episode)
    result = paired_trial(
        c2_episode, cutoff,
        source="ws-41.corp.local", target="ext-c2-01.net",
    )
    assert result.cutoff_window == cutoff
    assert result.action["action_type"] == "block_edge"


def test_paired_trial_benign_disruption_is_measured(c2_episode) -> None:
    cutoff = _post_c2_cutoff(c2_episode)
    payload = paired_trial(
        c2_episode, cutoff,
        source="ws-41.corp.local", target="ext-c2-01.net",
    ).to_json()
    d = payload["service_disruption"]
    assert 0.0 <= d["benign_packet_loss_pct"] <= 100.0
    assert d["reversibility"].startswith("reversible")


def test_action_policy_release_blockers_disclosed() -> None:
    for blocker in ("kill switch", "scope allowlist", "audit integrity"):
        assert any(
            blocker in b for b in ACTION_POLICY["release_blockers_enforced"]
        )
