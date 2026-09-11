"""FORESIGHT offline console API (Build Spec Appendix L, K.2).

Local-only service connecting the analyst console to the REAL pipeline:
synthetic capture sessions -> packet telemetry -> eligible prefix windows ->
I.5 ensemble forecast with I.4 calibration -> committed ForecastRecord
(E.2/E.3) with publication receipts -> SENTINEL novelty -> deletion-tested
evidence. ``/reveal`` is the only evaluation-side truth source (SE02).

Structured errors follow L.2: ``code``/``message``/``request_id``/``details``
/``retryable``, with 422 invalid schema, 404 unknown resource, 409 conflict
and typed ``not_supported`` results for disabled scientific tasks.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import SCHEMA_ID
from ..actions import (
    ACTION_POLICY,
    ActionStateMachine,
    IllegalTransitionError,
)
from ..contracts.objects import full_packet_capability
from ..data.episodes import build_episode
from ..data.ctu import build_ctu_episode, build_ctu_pcap_episode
from ..ingest.ctu_adapter import parse_ctu_binetflow
from ..ingest.pcap_adapter import parse_pcap
from ..labels.ontology import SIH_TACTICS, TASK_DEFINITIONS
from .bundle import RuntimeBundle, load_bundle
from .service import CATALOG, EpisodeSession

REPO_ROOT = Path(__file__).resolve().parents[3]
#: The serving profile directory is overridable (FORESIGHT_PROFILE_DIR) so a
#: verified snapshot bundle can be served while a retrain rebuilds the
#: default location — the SE01 hash seal still applies to whatever loads.
PROFILE_DIR = Path(
    os.environ.get("FORESIGHT_PROFILE_DIR", REPO_ROOT / "artifacts" / "profile")
)
CTU_PROFILE_DIR = REPO_ROOT / "artifacts" / "ctu13" / "profile"
RUNTIME_STORE = REPO_ROOT / "artifacts" / "runtime-store"

_bundle: RuntimeBundle | None = None
_ctu_bundle: RuntimeBundle | None = None
_sessions: dict[str, EpisodeSession] = {}
_episode_cache: dict[tuple[str, int], object] = {}
MAX_SESSIONS = 32
MAX_ACTIONS = 256


def get_bundle() -> RuntimeBundle:
    global _bundle
    if _bundle is None:
        _bundle = load_bundle(PROFILE_DIR, config_path=REPO_ROOT / "configs" / "core.yaml")
    return _bundle


def get_ctu_bundle() -> RuntimeBundle:
    """Load the separately calibrated CTU profile; never silently fake it."""

    global _ctu_bundle
    if _ctu_bundle is None:
        if not (CTU_PROFILE_DIR / "manifest.json").exists():
            raise RuntimeError(
                "CTU profile is unavailable; run scripts/train_ctu_profile.py"
            )
        _ctu_bundle = load_bundle(
            CTU_PROFILE_DIR, config_path=REPO_ROOT / "configs" / "core.yaml"
        )
    return _ctu_bundle


def _storage():
    from ..storage.store import Storage

    return Storage(RUNTIME_STORE)


class CreateSession(BaseModel):
    catalog_id: str
    cutoff_window: int | None = None


class ForecastBody(BaseModel):
    cutoff_window: int | None = None
    horizon_bins: int | None = None


class EvidenceBody(BaseModel):
    entity: str
    task_index: int = 2
    cutoff_window: int | None = None


class RevealBody(BaseModel):
    cutoff_window: int | None = None


def _structured_error(
    request: Request, status: int, code: str, message: str, *, retryable=False, details=None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": message,
            "request_id": str(uuid.uuid4().hex[:12]),
            "details": details or {},
            "retryable": retryable,
        },
    )


app = FastAPI(title="FORESIGHT offline console", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return _structured_error(
        request, exc.status_code, f"http_{exc.status_code}", str(exc.detail)
    )


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """Numeric/unknown failures surface as typed 500s — never zero forecasts."""
    return _structured_error(
        request,
        500,
        "internal_error",
        "internal service error",
        retryable=True,
    )


# ---------------------------------------------------------------------------
# Health and catalog
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Liveness vs model readiness are distinct (L.1)."""
    ready = False
    try:
        bundle = get_bundle()
        ready = True
        trained = bundle.trained
        weights_profile = bundle.weights_profile
    except Exception:
        trained = False
        weights_profile = "bundle load failed"
    return {
        "status": "alive",
        "model_ready": ready,
        "trained": trained,
        "schema": SCHEMA_ID,
        "weights_profile": weights_profile,
        "sessions": len(_sessions),
        "action_mode": "demo_range",
        "tier_b": {
            "paths": "supported" if getattr(get_bundle(), "path_engine", None) else "not_supported",
            "queries": "supported",
            "actions": "demo_range",
        },
        "offline": True,
    }


@app.get("/v1/catalog")
def catalog() -> dict:
    """Available demonstration sessions (one curated episode per family)."""
    bundle = get_bundle()
    items = []
    for i, entry in enumerate(CATALOG):
        items.append(
            {
                "catalog_id": f"demo-{i:02d}",
                "campaign": entry["campaign"],
                "title": entry["title"],
                "summary": entry["summary"],
                "family": entry["campaign"],
                "synthetic": True,
                "source_format": "synthetic packet telemetry (disclosed)",
            }
        )
    ctu_path = REPO_ROOT / "artifacts" / "ctu13" / "raw" / "ctu13-scenario-06.binetflow"
    items.append(
        {
            "catalog_id": "ctu13-06-real",
            "campaign": "ctu13-scenario-06",
            "title": "CTU-13 scenario 6 real flow replay",
            "summary": (
                "Real labeled bidirectional network flows. Packet-only features are "
                "unavailable; Background remains separate from verified Normal."
            ),
            "family": "ctu13-real-flow",
            "synthetic": False,
            "available": ctu_path.exists() and (CTU_PROFILE_DIR / "manifest.json").exists(),
            "source_format": "CTU-13 binetflow (real capture-derived flows)",
        }
    )
    pcap_path = REPO_ROOT / "artifacts" / "ctu13" / "raw" / "ctu13-scenario-06-botnet-only.pcap"
    items.append(
        {
            "catalog_id": "ctu13-06-pcap-real",
            "campaign": "ctu13-scenario-06-pcap",
            "title": "CTU-13 scenario 6 packet replay",
            "summary": (
                "Real public botnet-only PCAP. Packet-header features are observed; "
                "flow features are derived by bounded segmentation."
            ),
            "family": "ctu13-real-pcap",
            "synthetic": False,
            "available": (
                pcap_path.exists() and ctu_path.exists()
                and (CTU_PROFILE_DIR / "manifest.json").exists()
            ),
            "source_format": "CTU-13 PCAP (real, botnet-only scope)",
        }
    )
    return {
        "catalog": items,
        "weights_profile": bundle.weights_profile,
        "trained": bundle.trained,
    }


@app.get("/v1/tasks")
def task_manifest() -> dict:
    return {
        "tasks": [
            {
                "task_index": t.task_index,
                "id": t.id,
                "label": t.label,
                "label_tier": t.label_tier,
                "description": t.description,
            }
            for t in TASK_DEFINITIONS
        ],
        "tactics": list(SIH_TACTICS),
        "note": (
            "Named targets only when their label manifest is qualified; "
            "unsupported targets return not_supported rather than zero risk "
            "(Section 11)."
        ),
    }


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def _build_catalog_episode(catalog_id: str):
    if catalog_id == "ctu13-06-pcap-real":
        flow_path = REPO_ROOT / "artifacts" / "ctu13" / "raw" / "ctu13-scenario-06.binetflow"
        pcap_path = REPO_ROOT / "artifacts" / "ctu13" / "raw" / "ctu13-scenario-06-botnet-only.pcap"
        if not flow_path.exists() or not pcap_path.exists():
            raise FileNotFoundError("qualified CTU-13 scenario 6 flow/PCAP files are not installed")
        key = (catalog_id, 0)
        if key not in _episode_cache:
            parsed = parse_ctu_binetflow(flow_path, scenario_id="06")
            packets = parse_pcap(pcap_path)
            _episode_cache[key] = build_ctu_pcap_episode(
                packets, parsed, partition=1, slice_index=0
            )
        return _episode_cache[key], {
            "title": "CTU-13 scenario 6 packet replay",
            "summary": "Real botnet-only packet capture with explicit scope limitations.",
        }
    if catalog_id == "ctu13-06-real":
        path = REPO_ROOT / "artifacts" / "ctu13" / "raw" / "ctu13-scenario-06.binetflow"
        if not path.exists():
            raise FileNotFoundError("qualified CTU-13 scenario 6 file is not installed")
        key = (catalog_id, 0)
        if key not in _episode_cache:
            parsed = parse_ctu_binetflow(path, scenario_id="06")
            _episode_cache[key] = build_ctu_episode(parsed, partition=1, slice_index=0)
        return _episode_cache[key], {
            "title": "CTU-13 scenario 6 real flow replay",
            "summary": "Real capture-derived flows with an explicit degraded capability profile.",
        }
    index = int(catalog_id.split("-")[1])
    entry = CATALOG[index]
    key = (entry["campaign"], entry["index"])
    if key not in _episode_cache:
        _episode_cache[key] = build_episode(entry["campaign"], entry["index"], seed=7000 + index)
    return _episode_cache[key], entry


@app.post("/v1/sessions", status_code=201)
def create_session(body: CreateSession) -> dict:
    if len(_sessions) >= MAX_SESSIONS:
        raise HTTPException(429, f"session quota reached ({MAX_SESSIONS})")
    try:
        episode, entry = _build_catalog_episode(body.catalog_id)
    except (IndexError, ValueError, FileNotFoundError):
        raise HTTPException(404, f"unknown catalog_id {body.catalog_id!r}") from None
    bundle = get_bundle()
    session = EpisodeSession(
        session_id=f"sess-{uuid.uuid4().hex[:12]}",
        episode=episode,
        bundle=bundle,
        storage=_storage(),
    )
    if body.cutoff_window is not None:
        if body.cutoff_window not in session.valid_cutoffs():
            raise HTTPException(
                422,
                f"cutoff_window must be one of {session.valid_cutoffs()}",
            )
    _sessions[session.session_id] = session
    return _session_summary(session, entry)


def _session_or_404(session_id: str) -> EpisodeSession:
    try:
        return _sessions[session_id]
    except KeyError:
        raise HTTPException(404, "unknown session") from None


def _session_summary(session: EpisodeSession, entry: dict | None = None) -> dict:
    episode = session.episode
    return {
        "session_id": session.session_id,
        "episode_id": episode.episode_id,
        "campaign": episode.campaign,
        "title": entry["title"] if entry else episode.campaign,
        "summary": entry["summary"] if entry else "",
        "created_at": session.created_at,
        "cutoff_window": max(session.valid_cutoffs()),
        "valid_cutoffs": session.valid_cutoffs(),
        "entity_count": len(session.entity_ids),
        "synthetic": bool(episode.capture.synthetic),
        "weights_profile": session.bundle.weights_profile,
    }


@app.get("/v1/sessions")
def list_sessions() -> dict:
    return {"sessions": [_session_summary(s) for s in _sessions.values()]}


@app.get("/v1/sessions/{session_id}")
def session_detail(session_id: str) -> dict:
    session = _session_or_404(session_id)
    capture = session.episode.capture
    summary = _session_summary(session)
    summary.update(
        {
            "history_windows": 20,
            "parse_status": "qualified",
            "observation_count": int(len(capture.packets)),
            "observation_unit": (
                "packet" if capture.family == "ctu13-real-pcap" else
                "flow" if capture.family == "ctu13-real-flow" else "packet"
            ),
            "capabilities": {
                "node_input": 88,
                "edge_input": 22,
                "global_input": 48,
                "flow_features": (
                    capture.capabilities is None
                    or "flow_lifecycle" in capture.capabilities
                ),
                "packet_features": (
                    capture.capabilities is None
                    or "packet_timing" in capture.capabilities
                ),
                "encrypted_payload_visible": False,
                "offline": True,
            },
            "capability_report": (
                capture.capability_report.to_json()
                if capture.capability_report is not None
                else full_packet_capability().to_json()
            ),
            "quality_report": (
                capture.quality_report.to_json()
                if capture.quality_report is not None
                else None
            ),
            "data_disclosure": capture.source_disclosure,
            "observation_gaps": [
                {"host": h, "from_ns": str(f), "to_ns": str(t)}
                for h, f, t in capture.sensor_gaps
            ],
        }
    )
    return summary


# ---------------------------------------------------------------------------
# Forecast, evidence, reveal
# ---------------------------------------------------------------------------

@app.post("/v1/sessions/{session_id}/forecast")
def forecast(session_id: str, body: ForecastBody | None = None) -> dict:
    session = _session_or_404(session_id)
    cutoff = (
        body.cutoff_window if body and body.cutoff_window is not None
        else max(session.valid_cutoffs())
    )
    try:
        return session.run_forecast(cutoff)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post("/v1/sessions/{session_id}/evidence")
def evidence(session_id: str, body: EvidenceBody) -> dict:
    session = _session_or_404(session_id)
    cutoff = (
        body.cutoff_window if body.cutoff_window is not None
        else max(session.valid_cutoffs())
    )
    if body.entity not in session.entity_ids:
        raise HTTPException(
            422, f"unknown entity {body.entity!r} in this session"
        )
    if not 0 <= body.task_index < 5:
        raise HTTPException(422, "task_index must be in [0, 4]")
    try:
        return session.evidence(body.entity, body.task_index, cutoff)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post("/v1/sessions/{session_id}/reveal")
def reveal(session_id: str, body: RevealBody | None = None) -> dict:
    session = _session_or_404(session_id)
    cutoff = body.cutoff_window if body and body.cutoff_window is not None else None
    return session.reveal(cutoff)


# ---------------------------------------------------------------------------
# Evaluation, queries (typed disabled), actions (disabled)
# ---------------------------------------------------------------------------

@app.get("/v1/evaluation")
def evaluation() -> dict:
    """Locked-test evaluation report from the trained run + golden examples."""
    import json
    import math

    from ..models.survival import (
        conditional_eta,
        distribution_from_hazards,
    )
    from ..runtime.forecast import DEFAULT_DISPLAY_ETA_THRESHOLD

    bundle = get_bundle()
    hazards = torch.tensor([0.10, 0.20, 0.30], dtype=torch.float64)
    dist = distribution_from_hazards(hazards, bin_seconds=30)
    eta = conditional_eta(
        dist, min_occurrence_probability=DEFAULT_DISPLAY_ETA_THRESHOLD
    )
    golden = {
        "hazards": [0.10, 0.20, 0.30],
        "cumulative_risk": [round(float(v), 6) for v in dist.cumulative_risk],
        "no_event_mass": round(float(dist.no_event_mass), 6),
        "expected_cumulative_risk": [0.10, 0.28, 0.496],
        "expected_no_event_mass": 0.504,
        "cumulative_matches": all(
            math.isclose(float(a), b, abs_tol=1e-9)
            for a, b in zip(dist.cumulative_risk, [0.10, 0.28, 0.496])
        ),
        "no_event_matches": math.isclose(
            float(dist.no_event_mass), 0.504, abs_tol=1e-9
        ),
        "conditional_median_bin": eta.median_bin if eta else None,
        "expected_median_bin": 2,
        "eta_reported": eta is not None,
    }

    report_path = PROFILE_DIR / "evaluation_report.json"
    report = None
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "weights_profile": bundle.weights_profile,
        "trained": bundle.trained,
        "golden_example_1": golden,
        "locked_test_report": report,
        "note": (
            "Statistical targets are evidence about the synthetic corpus, "
            "not measured real-world performance (Build Spec Section 6)."
        ) if report else (
            "No locked-test report yet: run scripts/train_profile.py then "
            "scripts/evaluate_profile.py"
        ),
    }


# ---------------------------------------------------------------------------
# Tier B: evidence queries (Section 21) and range actions (Sections 22-23)
# ---------------------------------------------------------------------------

class QueryProposeBody(BaseModel):
    session_id: str
    cutoff_window: int


class QueryExecuteBody(BaseModel):
    session_id: str
    cutoff_window: int


@app.post("/v1/queries")
def queries(body: QueryProposeBody) -> dict:
    """Tier B evidence requests: transparent-rule proposals from the
    committed forecast (Section 21 default stretch policy)."""
    session = _session_or_404(body.session_id)
    try:
        return session.propose_queries(body.cutoff_window)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.post("/v1/queries/{proposal_id}/execute")
def query_execute(proposal_id: str, body: QueryExecuteBody) -> dict:
    """Execute one allowlisted request: answered / unavailable / denied /
    expired — never an invented observation (N.3)."""
    session = _session_or_404(body.session_id)
    try:
        answer = session.execute_query(proposal_id, body.cutoff_window)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    _audit_event(
        "query_executed",
        {
            "proposal_id": proposal_id,
            "entity": answer.get("entity"),
            "status": answer.get("status"),
            "cutoff_window": body.cutoff_window,
            "forecast_version": answer.get("forecast_version"),
        },
    )
    return answer


# -- actions (synthetic range only, disclosed) ------------------------------

class ActionProposeBody(BaseModel):
    session_id: str
    cutoff_window: int
    source: str
    target: str


class ActionAuthorizeBody(BaseModel):
    signature: str | None = None  # demo: the analyst's explicit console click


class ActionExecuteBody(BaseModel):
    dry_run: bool = True


_actions: dict[str, "ActionStateMachine"] = {}


def _audit_event(kind: str, payload: dict) -> None:
    """Durable audit record (Section 23 audit integrity). The audit sink
    must never break the action/query planes — on storage failure the
    in-memory trail remains the primary record for the offline demo."""
    try:
        storage = _storage()
        try:
            storage.meta.audit("local", kind, payload)
        finally:
            storage.close()
    except Exception:  # noqa: BLE001 - audit is best-effort durable
        pass


@app.get("/v1/actions")
def actions_status() -> dict:
    """Action plane status + reconciler pass (Section 23: TTL and recovery
    enforced even if the planner or UI crashed)."""
    for machine in _actions.values():
        before = machine.status
        machine.reconcile()
        if machine.status != before:
            _audit_event(
                "action_transition",
                {"event": machine.status, "action_id": machine.proposal.action_id},
            )
    return {
        "mode": "demo_range",
        "disclosure": (
            "execution happens in the disclosed synthetic range only; no "
            "real-world control effect is claimed (Sections 2, 22-23)"
        ),
        "policy": ACTION_POLICY,
        "actions": [m.to_json() for m in _actions.values()],
    }


@app.post("/v1/actions/propose")
def actions_propose(body: ActionProposeBody) -> dict:
    """Propose one block_edge action bound to the committed forecast at the
    cutoff; policy failures are reported, never silently coerced."""
    from ..actions import new_proposal, check_policy

    session = _session_or_404(body.session_id)
    if not session.episode.capture.synthetic:
        raise HTTPException(
            409,
            "actions are not supported for fixed real captures; the paired "
            "causal range is synthetic and separately disclosed",
        )
    if len(_actions) >= MAX_ACTIONS:
        raise HTTPException(429, f"action quota reached ({MAX_ACTIONS})")
    payload = session.forecast_cache.get(body.cutoff_window)
    if payload is None:
        raise HTTPException(
            409,
            "run the forecast at this cutoff before proposing an action",
        )
    record = payload.get("record") or {}
    # Observed pairs for the scope check: eligible-prefix telemetry, both
    # directions, including cross-boundary (internal<->external) pairs —
    # graph edges are internal-only (G.2).
    graph = payload.get("graph", {})
    observed = {
        (e["source"], e["target"])
        for e in graph.get("observed_edges", [])
    } | {
        (e["source"], e["target"])
        for e in graph.get("external_edges", [])
    }
    observed |= {(b, a) for (a, b) in observed}
    failures = check_policy(
        action_type="block_edge",
        source=body.source,
        target=body.target,
        forecast_id=record.get("forecast_id", ""),
        forecast_hash=record.get("forecast_hash", ""),
        observed_pairs=sorted(observed),
    )
    disagreement = None
    for entity in payload.get("entities", []):
        if entity["name"] in (body.source, body.target):
            for task in entity.get("tasks", []):
                if task.get("task_index") == 2:
                    disagreement = task.get("disagreement")
    proposal = new_proposal(
        source=body.source,
        target=body.target,
        forecast_id=record.get("forecast_id", ""),
        forecast_hash=record.get("forecast_hash", ""),
        cutoff_window=body.cutoff_window,
        session_id=body.session_id,
        uncertainty=(
            {"ensemble_disagreement_lateral": disagreement}
            if disagreement is not None
            else {}
        ),
    )
    machine = ActionStateMachine(proposal, policy_failures=failures)
    _actions[proposal.action_id] = machine
    _audit_event(
        "action_transition",
        {
            "event": "proposed",
            "action_id": proposal.action_id,
            "status": machine.status,
            "action_type": proposal.action_type,
            "parameters": {"source": proposal.source, "target": proposal.target},
            "forecast_hash": proposal.forecast_hash,
            "cutoff_window": proposal.cutoff_window,
            "policy_version": proposal.policy_version,
            "policy_failures": failures,
        },
    )
    return machine.to_json()


@app.post("/v1/actions/{action_id}/authorize")
def actions_authorize(action_id: str, body: ActionAuthorizeBody) -> dict:
    """Explicit human authorization. In the demo the console click produces
    the HMAC signature (disclosed demo key, Section 23 signed-approval
    contract); production authorization is a separate service."""
    from ..actions import sign_approval

    machine = _actions.get(action_id)
    if machine is None:
        raise HTTPException(404, "unknown action")
    signature = body.signature or sign_approval(machine.proposal)
    try:
        machine.authorize(signature)
    except IllegalTransitionError as exc:
        raise HTTPException(409, str(exc)) from None
    _audit_event(
        "action_transition",
        {
            "event": "authorized",
            "action_id": machine.proposal.action_id,
            "status": machine.status,
            "idempotency_key": machine.proposal.idempotency_key,
        },
    )
    return machine.to_json()


@app.post("/v1/actions/{action_id}/execute")
def actions_execute(action_id: str, body: ActionExecuteBody) -> dict:
    """Execute once in the synthetic range: a paired no-action/action trial
    from the same cutoff, same seed (Section 22). Dry-run is the default
    (kill switch); outcomes are audit-logged with verified postconditions."""
    from ..actions import paired_trial

    machine = _actions.get(action_id)
    if machine is None:
        raise HTTPException(404, "unknown action")
    try:
        machine.begin_execution()
    except IllegalTransitionError as exc:
        raise HTTPException(409, str(exc)) from None
    proposal = machine.proposal
    session = _sessions.get(proposal.session_id)
    if session is None or not session.record_ids.get(proposal.cutoff_window):
        machine.complete("failed", {"reason": "bound session no longer available"})
        raise HTTPException(409, "the bound session is no longer available")
    try:
        trial = paired_trial(
            session.episode,
            proposal.cutoff_window,
            source=proposal.source,
            target=proposal.target,
        )
    except ValueError as exc:
        machine.complete("failed", {"reason": str(exc)})
        raise HTTPException(422, str(exc)) from None
    outcome = trial.to_json()
    outcome["dry_run"] = body.dry_run
    status = "succeeded" if trial.postcondition_verified else "failed"
    machine.complete(status, outcome)
    result = machine.to_json()
    result["trial"] = outcome
    _audit_event(
        "action_transition",
        {
            "event": status,
            "action_id": proposal.action_id,
            "status": machine.status,
            "dry_run": body.dry_run,
            "postcondition_verified": trial.postcondition_verified,
            "averted_events": len(trial.averted_events),
            "packets_blocked": trial.action_arm.packets_blocked,
            "benign_packet_loss_pct": trial.service_disruption[
                "benign_packet_loss_pct"
            ],
        },
    )
    return result


@app.get("/v1/actions/{action_id}")
def action_detail(action_id: str) -> dict:
    machine = _actions.get(action_id)
    if machine is None:
        raise HTTPException(404, "unknown action")
    machine.reconcile()
    return machine.to_json()


_dist_dir = REPO_ROOT / "apps" / "console" / "dist"
if _dist_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_dist_dir), html=True), name="console")


def main() -> None:
    import uvicorn

    uvicorn.run(
        "foresight.api.server:app",
        host="127.0.0.1",
        port=int(os.environ.get("FORESIGHT_CONSOLE_PORT", "8001")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
