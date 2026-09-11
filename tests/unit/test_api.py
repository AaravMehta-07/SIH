"""API contract tests (Build Spec L.2, API01/API02 semantics).

Exercises the offline console service over the REAL pipeline with the
disclosed untrained fallback bundle: session catalog, forecast commit and
publication receipt, evidence provenance, reveal separation, typed disabled
results and structured errors.
"""

from __future__ import annotations

import os
import json

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


def test_forecast_provenance_is_sealed(client, lateral_session):
    """T.4/Section-7: every committed forecast binds its legal-prefix hash,
    source-object hashes and verified artifact hashes."""
    sid = lateral_session["session_id"]
    cutoff_a = lateral_session["valid_cutoffs"][0]
    cutoff_b = lateral_session["valid_cutoffs"][1]
    a = client.post(
        f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff_a}
    ).json()
    b = client.post(
        f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff_b}
    ).json()

    def check(payload):
        prov = payload["record"]["provenance"]
        assert len(prov["legal_prefix_hash"]) == 64
        assert "eligible" in prov["eligibility_rule_id"]
        assert len(prov["source_object_hashes"]["capture"]) == 64
        artifacts = prov["artifact_hashes"]
        assert artifacts["scaler"] and artifacts["config"]
        assert artifacts["selection_policy"]
        assert all(len(h) == 64 for h in artifacts["models"].values())
        assert artifacts["models"], "member weights hashes are cited"
        assert prov["runtime_profile"]
        assert prov["omitted_computations"], "engine omissions are disclosed"
        return prov

    prov_a = check(a)
    prov_b = check(b)
    # same source object and artifacts across cutoffs; the PREFIX hash
    # differs because the eligibility window differs
    assert (
        prov_a["source_object_hashes"]["capture"]
        == prov_b["source_object_hashes"]["capture"]
    )
    assert (
        prov_a["artifact_hashes"]["models"]
        == prov_b["artifact_hashes"]["models"]
    )
    assert prov_a["legal_prefix_hash"] != prov_b["legal_prefix_hash"]


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


def test_action_lifecycle_writes_durable_audit(
    client, lateral_session, monkeypatch, tmp_path
):
    """Section 23 audit integrity: every action lifecycle transition and
    query execution lands in the durable audit log, not only in memory."""
    import sqlite3

    monkeypatch.setattr(server, "RUNTIME_STORE", tmp_path)
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
    client.post(f"/v1/actions/{proposal['action_id']}/authorize", json={})
    executed = client.post(
        f"/v1/actions/{proposal['action_id']}/execute", json={"dry_run": True}
    )
    assert executed.status_code == 200, executed.text

    conn = sqlite3.connect(tmp_path / "metadata.sqlite3")
    try:
        rows = conn.execute(
            "SELECT kind, payload_json FROM audit_events ORDER BY at_ns"
        ).fetchall()
    finally:
        conn.close()
    kinds = [k for k, _ in rows]
    assert kinds.count("action_transition") >= 3  # proposed, authorized, terminal
    events = [json.loads(p) for _, p in rows]
    assert any(e["event"] == "proposed" for e in events)
    assert any(e["event"] == "authorized" for e in events)
    assert any(
        e["event"] in ("succeeded", "failed") and "postcondition_verified" in e
        for e in events
    )


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


def test_console_api_shapes_round_trip_real_server_payloads(client, lateral_session):
    """UI01: JSON produced by the server contains every field consumed by
    ``apps/console/src/types.ts`` for the main session/forecast/query path."""

    sid = lateral_session["session_id"]
    detail = json.loads(json.dumps(client.get(f"/v1/sessions/{sid}").json()))
    for key, expected in {
        "session_id": str,
        "valid_cutoffs": list,
        "synthetic": bool,
        "capability_report": dict,
        "capabilities": dict,
        "observation_count": int,
        "observation_unit": str,
    }.items():
        assert isinstance(detail[key], expected), key
    assert all(
        {"field_group", "state", "reason", "source_count"} <= set(field)
        for field in detail["capability_report"]["fields"]
    )

    cutoff = detail["valid_cutoffs"][0]
    forecast = json.loads(json.dumps(client.post(
        f"/v1/sessions/{sid}/forecast", json={"cutoff_window": cutoff}
    ).json()))
    assert {
        "weights_profile", "model", "horizon_bins", "bin_seconds", "entities",
        "graph", "novelty", "flagged", "coverage", "paths", "record",
    } <= set(forecast)
    assert all(
        {"task_index", "status", "cumulative_risk", "no_event_mass", "alerting", "trust"}
        <= set(task)
        for entity in forecast["entities"] for task in entity["tasks"]
    )
    queries = json.loads(json.dumps(client.post(
        "/v1/queries", json={"session_id": sid, "cutoff_window": cutoff}
    ).json()))
    assert {"cutoff_window", "policy", "identity_quality", "proposals", "note"} <= set(queries)
    assert isinstance(queries["identity_quality"]["coverage"]["covered_hosts"], list)
