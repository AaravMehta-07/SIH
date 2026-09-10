"""Operational state axes (Build Spec Section 18).

Orthogonal axes, never one exclusive enum: forecast support, threat evidence,
novelty, health and action authority coexist. The compatibility UI may show
NORMAL/ELEVATED/NOVEL/DEGRADED but MUST retain the full axes (Section 18).
"""

from __future__ import annotations

from dataclasses import dataclass

FORECAST_SUPPORT = ("supported", "exploratory", "abstained", "unsupported")
THREAT_EVIDENCE = ("low", "elevated", "confirmed_observation")
NOVELTY = ("reference_like", "novel", "unavailable")
HEALTH = ("healthy", "degraded", "stale", "failed")
ACTION_AUTHORITY = ("observe", "recommend", "approved", "executing", "blocked")

#: Wire enum for unsupported predictions (D.1: exactly one spelling).
NOT_SUPPORTED_WIRE = "not_supported"

#: J.3 reason codes.
REASON_CODES = (
    "insufficient_history",
    "packet_channel_missing",
    "identity_ambiguous",
    "scope_truncated",
    "unsupported_task",
    "unsupported_horizon",
    "calibration_regime_unknown",
    "stale_sensor",
    "artifact_mismatch",
    "numeric_failure",
    "parser_failure",
    "deadline_exceeded",
)


@dataclass(frozen=True)
class SupportStatus:
    """Per-task forecast support decision with explicit reason codes (J.3)."""

    status: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in FORECAST_SUPPORT:
            raise ValueError(f"unknown support status {self.status!r}")
        for reason in self.reasons:
            if reason not in REASON_CODES:
                raise ValueError(f"unknown reason code {reason!r}")

    @classmethod
    def supported(cls) -> "SupportStatus":
        return cls("supported")

    @classmethod
    def abstain(cls, *reasons: str) -> "SupportStatus":
        return cls("abstained", reasons)

    @classmethod
    def not_supported(cls, *reasons: str) -> "SupportStatus":
        return cls("unsupported", reasons)


@dataclass(frozen=True)
class HealthState:
    """Runtime/component health along the Section-18 health axis."""

    status: str
    component: str = "runtime"
    detail: str = ""

    def __post_init__(self) -> None:
        if self.status not in HEALTH:
            raise ValueError(f"unknown health status {self.status!r}")
