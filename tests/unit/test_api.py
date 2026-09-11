"""API contract tests (Build Spec L.2, API01/API02 semantics).

Exercises the offline console service over the REAL pipeline with the
disclosed untrained fallback bundle: session catalog, forecast commit and
publication receipt, evidence provenance, reveal separation, typed disabled
results and structured errors.
"""

from __future__ import annotations

import os

os.environ.setdefault("FORESIGHT_CONSOLE_PORT", "8021")

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from foresight.api import server  # noqa: E402


@pytest.fixture(scope="module")
def client():
    server._bundle = None
    server._sessions.clear()
    return TestClient(server.app)


@pytest.fixture(scope="module")
def lateral_session(client):
    catalog = client.get("/v1/catalog").json()["catalog"]
    entry = next(c for c in catalog if "lateral" in c["campaign"])
    resp = client.post("/v1/sessions", json={"catalog_id": entry["catalog_id"]})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_health_liveness_vs_readiness(client):
    body = client.get("/health").json()
    assert body["status"] == "alive"
    assert body["model_ready"] is True
    assert body["schema"] == "foresight.core.2026-09"
    assert "weights_profile" in body


def test_catalog_lists_all_families(client):
    body = client.get("/v1/catalog").json()
    campaigns = {item["campaign"] for item in body["catalog"]}
    assert "benign-baseline" in campaigns
    assert "web-to-lateral" in campaigns
    assert "c2-exfil" in campaigns


def test_task_manifest_five_targets_with_tiers(client):
    body = client.get("/v1/tasks").json()
    assert len(body["tasks"]) == 5
    assert body["tasks"][0]["label_tier"] == "weak_proxy"
    assert body["tasks"][0]["id"] == "malicious-endpoint-contact"


def test_forecast_commits_and_publishes(client, lateral_session):
    sid = lateral_session["session_id"]
    cutoff = lateral_session["valid_cutoffs"][0]
    resp = client.post(
        f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cutoff_window"] == cutoff
    assert body["horizon_bins"] == 60
    record = body["record"]
    assert record["committed"] is True
    assert record["forecast_hash"]
    assert record["published_at_ns"]  # E.3: publication receipt exists
    # monotone cumulative risk, probability conservation (D.7 validation)
    for entity in body["entities"]:
        for task in entity["tasks"]:
            if task["cumulative_risk"] is None:
                assert task["status"] != "supported"
                continue
            cum = task["cumulative_risk"]
            assert all(b >= a - 1e-9 for a, b in zip(cum, cum[1:]))
            assert -1e-9 <= cum[-1] <= 1 + 1e-9


def test_forecast_unknown_session_404(client):
    resp = client.post("/v1/sessions/does-not-exist/forecast", json={})
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "http_404"
    assert "request_id" in body


def test_forecast_invalid_cutoff_422(client, lateral_session):
    resp = client.post(
        f"/v1/sessions/{lateral_session['session_id']}/forecast",
        json={"cutoff_window": 3},
    )
    assert resp.status_code == 422


def test_evidence_links_legal_prefix_rows(client, lateral_session):
    sid = lateral_session["session_id"]
    resp = client.post(
        f"/v1/sessions/{sid}/evidence",
        json={"entity": "web-01.dmz.local", "task_index": 2},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entity"] == "web-01.dmz.local"
    # every cited flow belongs to the episode-bounded legal prefix (EX02)
    for flow in body["flows"]:
        assert 0 <= flow["window"] < 110


def test_evidence_unknown_entity_422(client, lateral_session):
    resp = client.post(
        f"/v1/sessions/{lateral_session['session_id']}/evidence",
        json={"entity": "not-a-host", "task_index": 2},
    )
    assert resp.status_code == 422


def test_reveal_returns_ground_truth(client, lateral_session):
    sid = lateral_session["session_id"]
    cutoff = lateral_session["valid_cutoffs"][0]
    client.post(f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff})
    resp = client.post(
        f"/v1/sessions/{sid}/reveal", json={"cutoff_window": cutoff}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["cutoff_window"] == cutoff
    tasks = {e["task_index"] for e in body["events"]}
    assert 1 in tasks and 2 in tasks  # initial access + lateral movement


def test_queries_require_known_session(client):
    resp = client.post(
        "/v1/queries", json={"session_id": "sess-nope", "cutoff_window": 40}
    )
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "http_404"


def test_queries_real_tier_b_flow(client, lateral_session):
    """Section 21 evidence requests: proposals from the committed forecast,
    typed execution states, 422 on unknown proposals."""
    sid = lateral_session["session_id"]
    cutoff = lateral_session["valid_cutoffs"][5]
    forecast = client.post(
        f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff}
    )
    assert forecast.status_code == 200
    resp = client.post(
        "/v1/queries", json={"session_id": sid, "cutoff_window": cutoff}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["policy"]["query_type"] == "identity_session_detail"
    assert body["identity_quality"]["parsed_rows"] > 0
    for p in body["proposals"]:
        assert p["cost"]["privacy"] > 0
        assert p["status"] == "proposed"
    # unknown proposal: typed 422, never a crash
    bad = client.post(
        "/v1/queries/qp-nope/execute",
        json={"session_id": sid, "cutoff_window": cutoff},
    )
    assert bad.status_code == 422


def test_actions_propose_policy_checked(client, lateral_session):
    """Sections 22-23: proposals bind the forecast hash; unobserved or
    internal-only pairs fail the scope allowlist and stay unauthorized."""
    sid = lateral_session["session_id"]
    cutoff = lateral_session["valid_cutoffs"][5]
    forecast = client.post(
        f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff}
    )
    assert forecast.status_code == 200
    # observed cross-boundary pair (the web server beacons to C2)
    ok = client.post(
        "/v1/actions/propose",
        json={
            "session_id": sid,
            "cutoff_window": cutoff,
            "source": "web-01.dmz.local",
            "target": "ext-c2-01.net",
        },
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["action_type"] == "block_edge"
    assert body["authorizable"] is True
    assert body["evidence_binding"]["forecast_hash"]
    assert any(a["action"] == "no_action" for a in body["alternatives"])

    # internal-only pair: scope allowlist rejects it
    internal = client.post(
        "/v1/actions/propose",
        json={
            "session_id": sid,
            "cutoff_window": cutoff,
            "source": "web-01.dmz.local",
            "target": "srv-app-02.corp.local",
        },
    )
    assert internal.status_code == 200
    assert internal.json()["authorizable"] is False

    # execution without authorization is a typed 409 (Section 23)
    denied = client.post(
        f"/v1/actions/{body['action_id']}/execute", json={"dry_run": True}
    )
    assert denied.status_code == 409


def test_actions_authorize_and_execute_paired_trial(client, lateral_session):
    """The full Section-23 lifecycle: authorize -> execute once -> paired
    trial outcome with a verified postcondition."""
    sid = lateral_session["session_id"]
    cutoff = lateral_session["valid_cutoffs"][5]
    client.post(f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff})
    proposal = client.post(
        "/v1/actions/propose",
        json={
            "session_id": sid,
            "cutoff_window": cutoff,
            "source": "web-01.dmz.local",
            "target": "ext-c2-01.net",
        },
    ).json()
    assert proposal["authorizable"] is True

    authorized = client.post(
        f"/v1/actions/{proposal['action_id']}/authorize", json={}
    )
    assert authorized.status_code == 200
    assert authorized.json()["status"] == "authorized"

    executed = client.post(
        f"/v1/actions/{proposal['action_id']}/execute", json={"dry_run": True}
    )
    assert executed.status_code == 200, executed.text
    result = executed.json()
    assert result["status"] in ("succeeded", "failed")
    trial = result["trial"]
    assert trial["cutoff_window"] == cutoff
    assert "no_action" in trial and "action_arm" in trial
    assert trial["dry_run"] is True
    # executing twice: idempotency key consumed (Section 23)
    again = client.post(
        f"/v1/actions/{proposal['action_id']}/execute", json={"dry_run": True}
    )
    assert again.status_code == 409


def test_evaluation_golden_example(client):
    body = client.get("/v1/evaluation").json()
    golden = body["golden_example_1"]
    assert golden["cumulative_matches"] is True
    assert golden["no_event_matches"] is True
    assert golden["conditional_median_bin"] == 2


def test_forecast_determinism_same_cutoff(client, lateral_session):
    sid = lateral_session["session_id"]
    cutoff = lateral_session["valid_cutoffs"][0]
    a = client.post(f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff}).json()
    b = client.post(f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff}).json()
    assert a["record"]["forecast_hash"] == b["record"]["forecast_hash"]
