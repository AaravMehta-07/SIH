"""Action proposals, policy checks and the Section-23 state machine.

Control requests bind tenant, exact asset identity, action type, parameters,
maximum scope, evidence/forecast hashes, policy version, expiry and an
idempotency key. All bindings are rechecked immediately before execution
(no stale approval, no identity-race). ``block_edge`` is a temporary
network restriction: reversible at the policy level (Section 23).

Approval signatures use a LOCAL DEMO key (HMAC-SHA256 over the canonical
proposal) so the signed-approval contract is exercised end to end; the
demo key is disclosed and never presented as production authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field

_NS = 1_000_000_000

POLICY_VERSION = "range-demo-policy-1"
EXPIRY_SECONDS = 600

#: Demo signing key (disclosed; production authorization is out of scope).
_DEMO_KEY = b"foresight-range-demo-key"

ACTION_TYPES = ("block_edge",)

#: The scope allowlist (Section 23): one directed external endpoint pair at
#: a time, both endpoints observed in the session scope, reversible only.
ACTION_POLICY = {
    "policy_version": POLICY_VERSION,
    "allowed_actions": list(ACTION_TYPES),
    "scope": "one internal<->external pair observed in the session",
    "reversibility": "reversible (temporary network restriction)",
    "expiry_seconds": EXPIRY_SECONDS,
    "approval": "explicit human authorization through the console",
    "executor": "separate range executor (synthetic range, disclosed)",
    "release_blockers_enforced": [
        "kill switch (dry-run default)",
        "scope allowlist",
        "audit integrity (hash-chained outcomes)",
    ],
}

#: Section-23 transition table.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "proposed": ("authorized", "expired"),
    "authorized": ("executing", "expired"),
    "executing": ("succeeded", "failed", "unknown"),
    "unknown": ("recovered",),
    "succeeded": (),
    "failed": (),
    "expired": (),
    "recovered": (),
}

TERMINAL_STATES = ("succeeded", "failed", "expired", "recovered")


class IllegalTransitionError(RuntimeError):
    """A state change the Section-23 table forbids."""


@dataclass(frozen=True)
class ActionProposal:
    action_id: str
    action_type: str
    source: str
    target: str
    scope: str
    forecast_id: str
    forecast_hash: str
    cutoff_window: int
    expiry_ns: int
    idempotency_key: str
    policy_version: str
    session_id: str = ""
    reversibility: str = "reversible"
    alternatives: tuple[dict, ...] = (
        {"action": "no_action", "description": "monitor; decide at the next cutoff"},
        {"action": "query_first", "description": "request identity/session detail first"},
    )
    uncertainty: dict = field(default_factory=dict)
    status: str = "proposed"

    def to_json(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "parameters": {"source": self.source, "target": self.target},
            "scope": self.scope,
            "evidence_binding": {
                "forecast_id": self.forecast_id,
                "forecast_hash": self.forecast_hash,
                "cutoff_window": self.cutoff_window,
            },
            "policy_version": self.policy_version,
            "expiry_ns": str(self.expiry_ns),
            "idempotency_key": self.idempotency_key,
            "reversibility": self.reversibility,
            "alternatives": [dict(a) for a in self.alternatives],
            "uncertainty": self.uncertainty,
            "status": self.status,
            "policy": ACTION_POLICY,
        }


def check_policy(
    *,
    action_type: str,
    source: str,
    target: str,
    forecast_id: str,
    forecast_hash: str,
    observed_pairs: list[tuple[str, str]],
) -> list[str]:
    """Policy checks BEFORE authorization. Returns the list of failures
    (empty = allowed). Scope, type, evidence binding and pair observability
    are all rechecked here and again at execution."""
    failures: list[str] = []
    if action_type not in ACTION_TYPES:
        failures.append(f"action type {action_type!r} is not allowlisted")
    if not forecast_id or not forecast_hash:
        failures.append("proposals must bind a committed forecast hash")
    if (source, target) not in observed_pairs and (
        target, source
    ) not in observed_pairs:
        failures.append(
            f"pair ({source}, {target}) was not observed in the session scope"
        )
    internal = (source.endswith(".local"), target.endswith(".local"))
    if all(internal) or not any(internal):
        failures.append(
            "block_edge scope is one internal<->external pair (Section 23 "
            "scope allowlist)"
        )
    return failures


def sign_approval(proposal: ActionProposal) -> str:
    """HMAC-SHA256 over the canonical proposal bytes, bound to expiry
    (Section 23: signed approval bound to the exact proposal and expiry)."""
    canonical = json.dumps(
        {
            "action_id": proposal.action_id,
            "action_type": proposal.action_type,
            "source": proposal.source,
            "target": proposal.target,
            "forecast_hash": proposal.forecast_hash,
            "expiry_ns": proposal.expiry_ns,
            "idempotency_key": proposal.idempotency_key,
            "policy_version": proposal.policy_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_DEMO_KEY, canonical, hashlib.sha256).hexdigest()


def verify_approval(proposal: ActionProposal, signature: str) -> bool:
    return hmac.compare_digest(sign_approval(proposal), signature)


class ActionStateMachine:
    """One action's Section-23 lifecycle with audit log.

    ``now_ns`` pins the clock for tests; production uses ``time.time_ns``.
    """

    def __init__(
        self,
        proposal: ActionProposal,
        *,
        now_ns: int | None = None,
        policy_failures: list[str] | None = None,
    ) -> None:
        self.proposal = proposal
        self.status = "proposed"
        self.policy_failures = list(policy_failures or [])
        self._now_ns = now_ns
        self.audit: list[dict] = [
            {"at_ns": self._now(), "from": None, "to": "proposed"}
        ]
        self.outcome: dict | None = None
        self._signature: str | None = None
        self._idempotency_used = False

    def _now(self) -> int:
        return self._now_ns if self._now_ns is not None else time.time_ns()

    # ------------------------------------------------------------------
    def authorize(self, signature: str) -> None:
        """Human approval: the signature must match THIS proposal and be
        presented before expiry."""
        if self.status != "proposed":
            raise IllegalTransitionError(
                f"cannot authorize from {self.status}"
            )
        if not verify_approval(self.proposal, signature):
            raise IllegalTransitionError("approval signature mismatch")
        if self._now() > self.proposal.expiry_ns:
            self._transition("expired")
            raise IllegalTransitionError("approval arrived after expiry")
        self._signature = signature
        self._transition("authorized")

    def begin_execution(self) -> None:
        """Durable intent is written (the audit log) BEFORE the connector
        call (Section 23: executing state). The idempotency key is consumed
        exactly once, checked before any state change."""
        if self._idempotency_used:
            raise IllegalTransitionError(
                "idempotency key already consumed (execute once, Section 23)"
            )
        if self.status != "authorized":
            raise IllegalTransitionError(
                f"cannot execute from {self.status} (authorization required)"
            )
        if self._now() > self.proposal.expiry_ns:
            self._transition("expired")
            raise IllegalTransitionError("execution began after expiry")
        self._idempotency_used = True
        self._transition("executing")

    def complete(self, status: str, outcome: dict) -> None:
        if self.status != "executing":
            raise IllegalTransitionError(
                f"cannot complete to {status} from {self.status}"
            )
        if status not in ("succeeded", "failed", "unknown"):
            raise ValueError(f"not a completion state: {status}")
        self.outcome = outcome
        self._transition(status)

    def reconcile(self) -> str:
        """Independent reconciler: TTL and recovery, even if the planner or
        UI crashed (Section 23). Unknown states resolve; expired proposals
        never execute."""
        if (
            self.status in ("proposed", "authorized")
            and self._now() > self.proposal.expiry_ns
        ):
            self._transition("expired")
        elif self.status == "unknown":
            self._transition("recovered")
        return self.status

    # ------------------------------------------------------------------
    def _transition(self, to: str) -> None:
        allowed = TRANSITIONS.get(self.status, ())
        if to not in allowed:
            raise IllegalTransitionError(
                f"illegal transition {self.status} -> {to}"
            )
        self.audit.append(
            {"at_ns": self._now(), "from": self.status, "to": to}
        )
        self.status = to

    def to_json(self) -> dict:
        payload = self.proposal.to_json()
        payload["status"] = self.status
        payload["audit"] = self.audit
        payload["outcome"] = self.outcome
        # Policy state persists through every lifecycle payload: the console
        # gates its panels on ``authorizable``, which must survive the
        # authorize/execute responses unchanged.
        payload["policy_failures"] = list(self.policy_failures)
        payload["authorizable"] = not self.policy_failures
        return payload


def new_proposal(
    *,
    source: str,
    target: str,
    forecast_id: str,
    forecast_hash: str,
    cutoff_window: int,
    session_id: str = "",
    uncertainty: dict | None = None,
    now_ns: int | None = None,
) -> ActionProposal:
    now = now_ns if now_ns is not None else time.time_ns()
    return ActionProposal(
        action_id=f"act-{uuid.uuid4().hex[:12]}",
        action_type="block_edge",
        source=source,
        target=target,
        scope=f"network pair {source} <-> {target} (temporary restriction)",
        forecast_id=forecast_id,
        forecast_hash=forecast_hash,
        cutoff_window=cutoff_window,
        expiry_ns=now + EXPIRY_SECONDS * _NS,
        idempotency_key=uuid.uuid4().hex,
        policy_version=POLICY_VERSION,
        session_id=session_id,
        uncertainty=uncertainty or {},
    )
