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


def test_queries_typed_disabled(client):
    resp = client.post("/v1/queries", json={"query": "process-tree"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_supported"


def test_actions_typed_disabled(client):
    resp = client.post("/v1/actions/propose", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_supported"


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
