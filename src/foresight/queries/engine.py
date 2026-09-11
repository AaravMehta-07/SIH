"""Evidence-request engine (Build Spec Section 21, N.3 answer contract)."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from ..ingest.identity import (
    IDENTITY_ELEVATED,
    identity_covered,
)
from ..ingest.identity import IdentityRecord

_NS = 1_000_000_000

#: The transparent stretch rule (Section 21): propose identity/session detail
#: when an entity's lateral-movement occurrence probability is ELEVATED
#: relative to the scope (>= RELATIVE_ELEVATION x the scope median for that
#: task, and above an absolute noise floor) but still UNCERTAIN (<= CAP — a
#: confident alarm does not need a query, it needs a decision). The band is
#: relative because calibrated probabilities on this profile live far below
#: absolute 0.15; the rule stays a disclosed transparent rule, not a
#: learned selector, and flat scopes (benign) propose nothing.
ABS_FLOOR = 0.03
RELATIVE_ELEVATION = 1.5
CAP = 0.85
UNCERTAIN_RULE = {
    "absolute_floor": ABS_FLOOR,
    "relative_elevation": RELATIVE_ELEVATION,
    "cap": CAP,
    "basis": (
        "lateral-movement occurrence probability above "
        f"{RELATIVE_ELEVATION}x the scope median and above {ABS_FLOOR}, but "
        f"at or below {CAP} (uncertain credential use)"
    ),
}

#: Lateral movement task index (credential use).
LATERAL_TASK = 2

QUERY_TYPE = "identity_session_detail"
EXPIRY_SECONDS = 300
QUERY_COST = {
    "privacy": 2,     # session subjects are exposed
    "compute": 1,
    "delay_seconds": 10,
}
ALLOWLIST = {
    QUERY_TYPE: {
        "scope": "one internal host with identity coverage per request",
        "cost": QUERY_COST,
        "expiry_seconds": EXPIRY_SECONDS,
        "policy_basis": (
            "Section 21 default stretch policy: identity/session detail for "
            "uncertain credential use"
        ),
    }
}


@dataclass(frozen=True)
class QueryProposal:
    proposal_id: str
    query_type: str
    entity: str
    task_index: int
    occurrence_probability: float
    rationale: str
    cost: dict
    expiry_ns: int
    created_ns: int

    def to_json(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "query_type": self.query_type,
            "entity": self.entity,
            "task_index": self.task_index,
            "occurrence_probability": round(self.occurrence_probability, 4),
            "rationale": self.rationale,
            "cost": self.cost,
            "expiry_ns": str(self.expiry_ns),
            "allowlist": ALLOWLIST[self.query_type],
            "status": "proposed",
        }


@dataclass
class QueryAnswer:
    proposal_id: str
    entity: str
    status: str                 # answered | unavailable | denied | expired
    reason: str
    records: list[dict] = field(default_factory=list)
    receipt_ns: int = 0
    forecast_version: int = 1

    def to_json(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "entity": self.entity,
            "status": self.status,
            "reason": self.reason,
            "records": self.records,
            "receipt_ns": str(self.receipt_ns),
            "forecast_version": self.forecast_version,
            "note": (
                "the answer is a new observation with its own clocks; it "
                "creates a new forecast version and never rewrites the "
                "committed seal. Identity telemetry is analyst context, not "
                "a model feature (Section 35 registry is frozen)"
            ),
        }


class QueryEngine:
    """Propose (transparent rule) and execute (allowlisted, typed states)
    evidence requests against the session's identity modality."""

    def __init__(
        self,
        identity_records: list[IdentityRecord],
        *,
        now_ns: int | None = None,
    ) -> None:
        self.records = identity_records
        self._now_ns = now_ns
        self._proposals: dict[str, QueryProposal] = {}
        self._answers: dict[str, QueryAnswer] = {}
        self.forecast_version = 1

    def _now(self) -> int:
        return self._now_ns if self._now_ns is not None else time.time_ns()

    # ------------------------------------------------------------------
    def propose(self, forecast_payload: dict, cutoff_window: int) -> list[dict]:
        """Transparent rule (Section 21): propose for entities whose
        lateral-movement probability is elevated relative to the scope
        median but not confidently alarming. Waiting and acting immediately
        remain the comparison policies."""
        now = self._now()
        lateral: list[tuple[str, float]] = []
        for entity in forecast_payload.get("entities", []):
            for task in entity.get("tasks", []):
                if task.get("task_index") != LATERAL_TASK:
                    continue
                prob = task.get("occurrence_probability")
                if prob is not None:
                    lateral.append((entity["name"], float(prob)))
        if not lateral:
            return []
        probs = sorted(p for _n, p in lateral)
        median = probs[len(probs) // 2]
        threshold = max(ABS_FLOOR, RELATIVE_ELEVATION * median)
        proposals: list[dict] = []
        for name, prob in lateral:
            if not (threshold < prob <= CAP):
                continue
            proposal = QueryProposal(
                proposal_id=f"qp-{uuid.uuid4().hex[:12]}",
                query_type=QUERY_TYPE,
                entity=name,
                task_index=LATERAL_TASK,
                occurrence_probability=prob,
                rationale=(
                    f"lateral-movement occurrence probability {prob:.3f} is "
                    f"elevated (scope median {median:.3f}, rule threshold "
                    f"{threshold:.3f}) yet not confidently alarming "
                    f"(<= {CAP}); identity/session detail for the credential "
                    "use could change the decision"
                ),
                cost=dict(QUERY_COST),
                expiry_ns=now + EXPIRY_SECONDS * _NS,
                created_ns=now,
            )
            self._proposals[proposal.proposal_id] = proposal
            proposals.append(proposal.to_json())
        return proposals

    # ------------------------------------------------------------------
    def execute(self, proposal_id: str, cutoff_ns: int) -> dict:
        """Answer one request. States: answered / unavailable / denied /
        expired. Answers never invent observations (Section 21)."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise ValueError(f"unknown query proposal {proposal_id!r}")
        if self._answers.get(proposal_id) is not None:
            return self._answers[proposal_id].to_json()
        now = self._now()
        if now > proposal.expiry_ns:
            answer = QueryAnswer(
                proposal_id, proposal.entity, "expired",
                "the request expired before execution (Section 21 expiry)",
                receipt_ns=now,
                forecast_version=self.forecast_version,
            )
        elif not identity_covered(proposal.entity):
            answer = QueryAnswer(
                proposal_id, proposal.entity, "unavailable",
                f"no identity sensor covers {proposal.entity} "
                "(missingness, not an observation)",
                receipt_ns=now,
                forecast_version=self.forecast_version,
            )
        elif proposal.entity in IDENTITY_ELEVATED:
            answer = QueryAnswer(
                proposal_id, proposal.entity, "denied",
                "querying identity on the domain controller requires "
                "elevated authorization (demo policy)",
                receipt_ns=now,
                forecast_version=self.forecast_version,
            )
        else:
            eligible = [
                r
                for r in self.records
                if (r.dest_host == proposal.entity or r.source_host == proposal.entity)
                and r.time_ns <= cutoff_ns
            ]
            self.forecast_version += 1
            answer = QueryAnswer(
                proposal_id,
                proposal.entity,
                "answered",
                (
                    f"{len(eligible)} session records on the legal prefix for "
                    f"{proposal.entity}"
                ),
                records=[r.to_json() for r in eligible[-24:]],
                receipt_ns=now,
                forecast_version=self.forecast_version,
            )
        self._answers[proposal_id] = answer
        return answer.to_json()

    # ------------------------------------------------------------------
    def status(self) -> dict:
        return {
            "query_type": QUERY_TYPE,
            "allowlist": ALLOWLIST[QUERY_TYPE],
            "uncertain_rule": UNCERTAIN_RULE,
            "comparison_policies": [
                "wait (no query, decide at the next cutoff)",
                "act immediately (no query)",
            ],
            "proposals": len(self._proposals),
            "answered": sum(
                1 for a in self._answers.values() if a.status == "answered"
            ),
            "forecast_version": self.forecast_version,
        }
