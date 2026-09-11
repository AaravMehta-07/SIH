"""Tier B identity adapter + evidence request tests (Sections 8, 21, N.3)."""

from __future__ import annotations

import pytest

from foresight.data.episodes import build_episode
from foresight.ingest.identity import (
    IDENTITY_ELEVATED,
    IdentityAdapter,
    generate_identity_log,
    identity_covered,
    identity_log_csv,
)
from foresight.queries import QueryEngine, UNCERTAIN_RULE


@pytest.fixture(scope="module")
def web_episode():
    return build_episode("web-to-lateral", 0, seed=7000)


@pytest.fixture(scope="module")
def cred_episode():
    return build_episode("cred-spray", 0, seed=7000)


# ---------------------------------------------------------------------------
# Identity log generation + adapter
# ---------------------------------------------------------------------------

def test_identity_log_deterministic(web_episode) -> None:
    a = generate_identity_log(web_episode)
    b = generate_identity_log(web_episode)
    assert a == b


def test_adapter_roundtrip_and_quality(web_episode) -> None:
    records = generate_identity_log(web_episode)
    parsed = IdentityAdapter().parse(identity_log_csv(records))
    assert parsed.total_rows == len(records)
    assert parsed.malformed_rows == 0
    assert len(parsed.records) == len(records)
    quality = parsed.quality_report
    assert quality["adapter"] == "identity-auth-csv"
    assert quality["parsed_rows"] == len(records)


def test_adapter_counts_malformed_rows() -> None:
    csv_text = (
        "time_ns,user,source_host,dest_host,auth_type,result,session_id\n"
        "1000,alice,ws-11.corp.local,dc-01.corp.local,kerberos,success,s-1\n"
        "notatime,bob,ws-11.corp.local,dc-01.corp.local,kerberos,success,s-2\n"
        "3000,carol,ws-11.corp.local,dc-01.corp.local,wrongtype,success,s-3\n"
        "4000,dave\n"
    )
    parsed = IdentityAdapter().parse(csv_text)
    assert parsed.total_rows == 4
    assert parsed.malformed_rows == 3
    assert len(parsed.records) == 1


def test_adapter_rejects_wrong_header() -> None:
    with pytest.raises(ValueError, match="header"):
        IdentityAdapter().parse("a,b,c\n1,2,3\n")


def test_canonical_auth_events(web_episode) -> None:
    from foresight.contracts.events import SecurityEvent

    parsed = IdentityAdapter().parse(
        identity_log_csv(generate_identity_log(web_episode))
    )
    events = IdentityAdapter().to_security_events(parsed)
    assert events and all(isinstance(e, SecurityEvent) for e in events)
    assert all(e.event_kind == "auth_observed" for e in events)
    # Section-7 clocks: available >= event, ingested >= available
    for e in events:
        assert e.event_time_lower_ns <= e.event_time_upper_ns
        assert e.available_at_ns >= e.event_time_upper_ns
        assert e.ingested_at_ns >= e.available_at_ns
    # an auth event is eligible at its ingested time (TM02 rule)
    assert events[0].eligible_at(events[0].ingested_at_ns)
    assert not events[0].eligible_at(events[0].ingested_at_ns - 1)


def test_lateral_chain_step_yields_remote_logon(web_episode) -> None:
    """The lateral chain step must surface as a remote logon pair — the
    answer the identity_session_detail query exists to return."""
    records = generate_identity_log(web_episode)
    lateral = [
        s for s in web_episode.chain if s.task_index == 2
    ]
    assert lateral, "web-to-lateral must script lateral movement"
    step = lateral[0]
    matches = [
        r for r in records
        if r.source_host == step.source
        and r.dest_host == step.target
        and r.auth_type == "remote"
        and r.result == "success"
    ]
    assert matches
    assert any(
        abs(r.time_ns - step.time_ns) < 1_000_000_000 for r in matches
    )


def test_cred_spray_yields_failure_burst(cred_episode) -> None:
    records = generate_identity_log(cred_episode)
    failures = [
        r for r in records
        if r.dest_host == "dc-01.corp.local" and r.result == "failure"
    ]
    assert len(failures) >= 40


def test_coverage_rules() -> None:
    assert identity_covered("ws-41.corp.local")
    assert not identity_covered("web-01.dmz.local")
    assert not identity_covered("ext-c2-01.net")


# ---------------------------------------------------------------------------
# Query engine
# ---------------------------------------------------------------------------

def _forecast_payload(entity: str, probability: float, peers: list[tuple[str, float]] | None = None) -> dict:
    """A scope whose lateral probabilities set the median; ``entity`` is the
    query candidate."""
    rows = {name: p for name, p in (peers or [])}
    rows[entity] = probability
    return {
        "entities": [
            {
                "name": name,
                "tasks": [{"task_index": 2, "occurrence_probability": p}],
            }
            for name, p in rows.items()
        ]
    }


# A typical trained-profile scope: flat median around 0.04.
PEERS = [(f"host-{i}", 0.04) for i in range(6)]


def test_proposal_rule_relative_elevation() -> None:
    engine = QueryEngine([], now_ns=1_000_000_000_000)
    # elevated above 1.5x the median but not alarming -> proposed
    proposals = engine.propose(
        _forecast_payload("ws-41.corp.local", 0.10, PEERS), 40
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p["query_type"] == "identity_session_detail"
    assert p["entity"] == "ws-41.corp.local"
    assert p["cost"]["privacy"] > 0
    # flat scope (benign): nothing is elevated -> no proposals
    flat = QueryEngine([], now_ns=1_000_000_000_000)
    assert flat.propose(_forecast_payload("host-0", 0.041, PEERS), 40) == []
    # confidently alarming: above the cap, needs a decision not a query
    alarmed = QueryEngine([], now_ns=1_000_000_000_000)
    assert alarmed.propose(_forecast_payload("ws-41.corp.local", 0.97, PEERS), 40) == []
    # pure noise below the absolute floor never proposes
    quiet = [(f"h-{i}", 0.005) for i in range(6)]
    quiet_engine = QueryEngine([], now_ns=1_000_000_000_000)
    assert quiet_engine.propose(_forecast_payload("h-0", 0.009, quiet), 40) == []


def test_rule_is_disclosed() -> None:
    assert UNCERTAIN_RULE["relative_elevation"] == 1.5
    assert UNCERTAIN_RULE["cap"] == 0.85
    assert "scope median" in UNCERTAIN_RULE["basis"]


def test_execute_answered_increments_version(web_episode) -> None:
    records = generate_identity_log(web_episode)
    engine = QueryEngine(records, now_ns=1_000_000_000_000)
    # ws-41 carries benign Kerberos logons from the episode start, so the
    # prefix genuinely holds session records at any cutoff >= 20.
    (proposal,) = engine.propose(
        _forecast_payload("ws-41.corp.local", 0.10, PEERS), 40
    )
    answer = engine.execute(proposal["proposal_id"], 40 * 30_000_000_000)
    assert answer["status"] == "answered"
    assert answer["forecast_version"] == 2
    assert engine.forecast_version == 2
    assert answer["records"], "an answered query returns real session records"
    # idempotent: executing again returns the same answer
    again = engine.execute(proposal["proposal_id"], 40 * 30_000_000_000)
    assert again["status"] == "answered"
    assert again["forecast_version"] == 2


def test_execute_unavailable_without_coverage(web_episode) -> None:
    records = generate_identity_log(web_episode)
    engine = QueryEngine(records, now_ns=1_000_000_000_000)
    (proposal,) = engine.propose(_forecast_payload("web-01.dmz.local", 0.10, PEERS), 40)
    answer = engine.execute(proposal["proposal_id"], 40 * 30_000_000_000)
    assert answer["status"] == "unavailable"
    assert "no identity sensor" in answer["reason"]


def test_execute_denied_on_elevated_target(web_episode) -> None:
    records = generate_identity_log(web_episode)
    engine = QueryEngine(records, now_ns=1_000_000_000_000)
    (proposal,) = engine.propose(_forecast_payload(IDENTITY_ELEVATED[0], 0.10, PEERS), 40)
    answer = engine.execute(proposal["proposal_id"], 40 * 30_000_000_000)
    assert answer["status"] == "denied"


def test_execute_expired(web_episode) -> None:
    records = generate_identity_log(web_episode)
    now = 1_000_000_000_000
    engine = QueryEngine(records, now_ns=now)
    (proposal,) = engine.propose(_forecast_payload("ws-41.corp.local", 0.10, PEERS), 40)
    engine._now_ns = now + 10 * 60 * 1_000_000_000 + 1  # past expiry
    answer = engine.execute(proposal["proposal_id"], 40 * 30_000_000_000)
    assert answer["status"] == "expired"


def test_unknown_proposal_rejected() -> None:
    engine = QueryEngine([], now_ns=1_000_000_000_000)
    with pytest.raises(ValueError, match="unknown query proposal"):
        engine.execute("qp-nope", 0)
