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
from ..contracts.objects import full_packet_capability
from ..data.episodes import build_episode
from ..labels.ontology import SIH_TACTICS, TASK_DEFINITIONS
from .bundle import RuntimeBundle, load_bundle
from .service import CATALOG, EpisodeSession

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = REPO_ROOT / "artifacts" / "profile"
RUNTIME_STORE = REPO_ROOT / "artifacts" / "runtime-store"

_bundle: RuntimeBundle | None = None
_sessions: dict[str, EpisodeSession] = {}
_episode_cache: dict[tuple[str, int], object] = {}


def get_bundle() -> RuntimeBundle:
    global _bundle
    if _bundle is None:
        _bundle = load_bundle(PROFILE_DIR, config_path=REPO_ROOT / "configs" / "core.yaml")
    return _bundle


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
        f"{type(exc).__name__}: {exc}",
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
        "action_mode": "disabled",
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
    index = int(catalog_id.split("-")[1])
    entry = CATALOG[index]
    key = (entry["campaign"], entry["index"])
    if key not in _episode_cache:
        _episode_cache[key] = build_episode(entry["campaign"], entry["index"], seed=7000 + index)
    return _episode_cache[key], entry


@app.post("/v1/sessions", status_code=201)
def create_session(body: CreateSession) -> dict:
    try:
        episode, entry = _build_catalog_episode(body.catalog_id)
    except (IndexError, ValueError):
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
        "synthetic": True,
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
            "packet_count": int(len(capture.packets)),
            "capabilities": {
                "node_input": 88,
                "edge_input": 22,
                "global_input": 48,
                "flow_and_packet_features": True,
                "encrypted_payload_visible": False,
                "offline": True,
            },
            "capability_report": full_packet_capability().to_json(),
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


@app.post("/v1/queries")
def queries(body: dict) -> dict:
    """Tier B evidence acquisition is not implemented: typed disabled result
    (L.2 - a successful typed response, never a misleading crash)."""
    return {
        "status": "not_supported",
        "reason": (
            "Tier B evidence-request queries are disabled in the core "
            "profile (Build Spec Section 21, Appendix N; T.3)"
        ),
        "request": body,
    }


@app.post("/v1/actions/propose")
def actions_propose(body: dict) -> dict:
    """Action authority is a separate control plane, disabled offline (Section 23)."""
    return {
        "status": "not_supported",
        "reason": (
            "action_mode is disabled in the offline core profile; FORESIGHT "
            "issues forecasts and evidence only (Build Spec Section 3, 23)"
        ),
        "request": body,
    }


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
