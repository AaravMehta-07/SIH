"""Canonical SecurityEvent and EntityRef records (Build Spec Sections 7-9, D.3).

``event_time`` is occurrence; ``available_at`` is earliest computability;
``ingested_at`` is local receipt (Section 7 — three distinct clocks). The
cutoff eligibility rule is implemented once here and used by every prefix
builder (TM02/TM03).

``observables`` payloads are typed per ``event_kind``; ingestion never accepts
a generic arbitrary dictionary (D.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .canonical import CanonicalJSONError, validate_opaque_id

SCHEMA = "foresight.core.2026-09"

EVENT_KINDS = (
    "packet_observed",
    "flow_segment_update",
    "flow_segment_closed",
    "sensor_health",
    "identity_binding",
    "auth_observed",
    "process_observed",
    "policy_snapshot",
)

ENTITY_TYPES = ("host", "address", "process", "service", "external")

#: Directional TCP flag bit positions in the packet record (Section 9).
TCP_FLAGS = ("syn", "ack", "fin", "rst", "psh", "urg")


class SupersedeError(RuntimeError):
    """A correction chain references an unknown or cyclic ``supersedes_event_id``."""


def _require_ns(value: int, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CanonicalJSONError(f"{name} must be int nanoseconds, got {value!r}")
    return value


@dataclass(frozen=True)
class EntityRef:
    """Section 8 entity reference with validity interval and link confidence."""

    tenant_id: str
    entity_id: str
    entity_type: str
    identity_version: int = 1
    valid_from_ns: int = 0
    valid_until_ns: int | None = None
    link_confidence: float = 1.0
    source_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_opaque_id(self.entity_id, field="entity_id")
        if self.entity_type not in ENTITY_TYPES:
            raise CanonicalJSONError(f"unknown entity_type {self.entity_type!r}")
        if not (0.0 <= self.link_confidence <= 1.0):
            raise CanonicalJSONError("link_confidence must be in [0, 1]")
        if self.valid_until_ns is not None and (
            self.valid_until_ns < self.valid_from_ns
        ):
            raise CanonicalJSONError("valid_until_ns must be >= valid_from_ns")

    def covers(self, at_ns: int) -> bool:
        if at_ns < self.valid_from_ns:
            return False
        return self.valid_until_ns is None or at_ns <= self.valid_until_ns

    def to_json(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "identity_version": self.identity_version,
            "valid_from_ns": str(self.valid_from_ns),
            "valid_until_ns": (
                None if self.valid_until_ns is None else str(self.valid_until_ns)
            ),
            "link_confidence": self.link_confidence,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True)
class PacketObservables:
    """Typed ``packet_observed`` payload (F.1 field allowlist).

    Payload content is never captured (F.1); only lengths, flags, timing and
    header fields the parser is allowed to see.
    """

    src_address: str
    dst_address: str
    protocol: str              # "tcp" | "udp" | "other"
    src_port: int | None
    dst_port: int | None
    captured_length: int
    wire_length: int
    transport_payload_length: int | None
    tcp_flags: tuple[bool, ...] = (False,) * 6  # syn ack fin rst psh urg order
    tcp_sequence: int | None = None
    tcp_window: int | None = None
    ip_ttl: int | None = None
    ip_fragmented: bool = False

    def __post_init__(self) -> None:
        if len(self.tcp_flags) != 6 or not all(
            isinstance(f, bool) for f in self.tcp_flags
        ):
            raise CanonicalJSONError("tcp_flags must be six booleans in syn..urg order")
        if self.protocol not in ("tcp", "udp", "other"):
            raise CanonicalJSONError(f"unknown protocol {self.protocol!r}")
        for name in ("captured_length", "wire_length"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise CanonicalJSONError(f"{name} must be a nonnegative int")
        if self.transport_payload_length is not None and (
            self.transport_payload_length < 0
        ):
            raise CanonicalJSONError("transport_payload_length must be >= 0")

    @property
    def flag_bits(self) -> dict[str, bool]:
        return dict(zip(TCP_FLAGS, self.tcp_flags))

    def to_json(self) -> dict[str, Any]:
        return {
            "src_address": self.src_address,
            "dst_address": self.dst_address,
            "protocol": self.protocol,
            "src_port": self.src_port,
            "dst_port": self.dst_port,
            "captured_length": self.captured_length,
            "wire_length": self.wire_length,
            "transport_payload_length": self.transport_payload_length,
            "tcp_flags": [bool(f) for f in self.tcp_flags],
            "tcp_sequence": self.tcp_sequence,
            "tcp_window": self.tcp_window,
            "ip_ttl": self.ip_ttl,
            "ip_fragmented": bool(self.ip_fragmented),
        }


@dataclass(frozen=True)
class SecurityEvent:
    """D.3 canonical normalized event.

    Clocks (Section 7): ``event_time_lower_ns <= event_time_upper_ns`` are
    occurrence bounds; ``available_at_ns`` is earliest computability (flow
    closure + processing delay for closed-flow fields); ``ingested_at_ns`` is
    local receipt. All three must be ``<= d`` for prefix eligibility.
    """

    tenant_id: str
    event_id: str
    sensor_id: str
    event_kind: str
    observables: PacketObservables | dict[str, Any]
    event_time_lower_ns: int
    event_time_upper_ns: int
    available_at_ns: int
    ingested_at_ns: int
    source_type: str = "synthetic"
    source_sequence: int | None = None
    ingest_sequence: int | None = None
    parser_hash: str = ""
    subjects: tuple[EntityRef, ...] = ()
    objects: tuple[EntityRef, ...] = ()
    validity: bool = True
    provenance_verified: bool = True
    source_event_ids: tuple[str, ...] = ()
    raw_object_hash: str = ""
    raw_pointer: dict[str, Any] = field(default_factory=dict)
    evidence_group_id: str = ""
    privacy_class: str = "synthetic"
    retention_class: str = "default"
    supersedes_event_id: str | None = None

    def __post_init__(self) -> None:
        validate_opaque_id(self.event_id, field="event_id")
        if self.event_kind not in EVENT_KINDS:
            raise CanonicalJSONError(f"unknown event_kind {self.event_kind!r}")
        _require_ns(self.event_time_lower_ns, "event_time_lower_ns")
        _require_ns(self.event_time_upper_ns, "event_time_upper_ns")
        _require_ns(self.available_at_ns, "available_at_ns")
        _require_ns(self.ingested_at_ns, "ingested_at_ns")
        if self.event_time_lower_ns > self.event_time_upper_ns:
            raise CanonicalJSONError(
                "event_time_lower_ns must be <= event_time_upper_ns"
            )
        if self.event_kind == "packet_observed" and not isinstance(
            self.observables, PacketObservables
        ):
            raise CanonicalJSONError(
                "packet_observed events require PacketObservables"
            )

    # -- Section 7 cutoff eligibility (single implementation, TM02/TM03) ----
    def eligible_at(self, cutoff_ns: int) -> bool:
        """eligible(field, d): all three clocks at or before d, provenance OK."""
        return (
            self.event_time_upper_ns <= cutoff_ns
            and self.available_at_ns <= cutoff_ns
            and self.ingested_at_ns <= cutoff_ns
            and self.provenance_verified
        )

    @property
    def event_time_ns(self) -> int:
        return self.event_time_upper_ns

    def to_json(self) -> dict[str, Any]:
        obs = (
            self.observables.to_json()
            if isinstance(self.observables, PacketObservables)
            else dict(self.observables)
        )
        return {
            "schema": SCHEMA,
            "tenant_id": self.tenant_id,
            "event_id": self.event_id,
            "sensor_id": self.sensor_id,
            "source_type": self.source_type,
            "source_sequence": self.source_sequence,
            "parser_hash": self.parser_hash,
            "event_time_lower_ns": str(self.event_time_lower_ns),
            "event_time_upper_ns": str(self.event_time_upper_ns),
            "available_at_ns": str(self.available_at_ns),
            "ingested_at_ns": str(self.ingested_at_ns),
            "event_kind": self.event_kind,
            "observables": obs,
            "subjects": [s.to_json() for s in self.subjects],
            "objects": [o.to_json() for o in self.objects],
            "validity": self.validity,
            "provenance_verified": self.provenance_verified,
            "source_event_ids": list(self.source_event_ids),
            "raw_object_hash": self.raw_object_hash,
            "raw_pointer": self.raw_pointer,
            "evidence_group_id": self.evidence_group_id,
            "privacy_class": self.privacy_class,
            "retention_class": self.retention_class,
            "supersedes_event_id": self.supersedes_event_id,
        }


def build_event(
    *,
    event_id: str,
    sensor_id: str,
    event_kind: str,
    observables: PacketObservables | dict[str, Any],
    event_time_ns: int,
    available_delay_ns: int = 0,
    ingest_delay_ns: int = 0,
    **kwargs: Any,
) -> SecurityEvent:
    """Convenience constructor: exact occurrence time, explicit delays.

    ``available_delay_ns`` models sensor/processing latency (e.g. flow closure);
    ``ingest_delay_ns`` models local receipt lag. Both default to zero, which
    makes synthetic fixture events immediately eligible at their event time.
    """
    return SecurityEvent(
        event_id=event_id,
        sensor_id=sensor_id,
        event_kind=event_kind,
        observables=observables,
        event_time_lower_ns=event_time_ns,
        event_time_upper_ns=event_time_ns,
        available_at_ns=event_time_ns + available_delay_ns,
        ingested_at_ns=event_time_ns + max(available_delay_ns, ingest_delay_ns),
        **kwargs,
    )
