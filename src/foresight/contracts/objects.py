"""Raw objects, capability reports and quality counters (D.2, D.4).

The parser never invents fields: every field group reports observed / derived
/ not_available / unreliable / not_applicable with a reason (D.4). Dropping
bad rows silently is prohibited — counters carry numerator and denominator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .canonical import CanonicalJSONError, sha256_hex, validate_opaque_id

FORMATS = ("pcap", "pcapng", "csv", "jsonl", "parquet")
PARSER_STATUSES = ("pending", "qualified", "rejected", "partial")
PRIVACY_CLASSES = ("synthetic", "restricted", "approved_public")

CAPABILITY_STATES = (
    "observed",
    "derived",
    "not_available",
    "unreliable",
    "not_applicable",
)


@dataclass(frozen=True)
class RawObject:
    """D.2 immutable uploaded/staged object. ``storage_key`` is server-generated."""

    object_id: str
    tenant_id: str
    sha256: str
    byte_length: int
    format: str
    original_display_name: str
    storage_key: str
    created_at_ns: int
    source_id: str
    privacy_class: str = "synthetic"
    retention_class: str = "default"
    parser_status: str = "pending"

    def __post_init__(self) -> None:
        validate_opaque_id(self.object_id, field="object_id")
        if self.format not in FORMATS:
            raise CanonicalJSONError(f"unknown object format {self.format!r}")
        if self.privacy_class not in PRIVACY_CLASSES:
            raise CanonicalJSONError(f"unknown privacy_class {self.privacy_class!r}")
        if self.parser_status not in PARSER_STATUSES:
            raise CanonicalJSONError(f"unknown parser_status {self.parser_status!r}")
        if len(self.sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.sha256
        ):
            raise CanonicalJSONError("sha256 must be 64 lowercase hex characters")
        if self.byte_length < 0:
            raise CanonicalJSONError("byte_length must be nonnegative")

    def to_json(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "tenant_id": self.tenant_id,
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "format": self.format,
            "original_display_name": self.original_display_name,
            "storage_key": self.storage_key,
            "created_at_ns": str(self.created_at_ns),
            "source_id": self.source_id,
            "privacy_class": self.privacy_class,
            "retention_class": self.retention_class,
            "parser_status": self.parser_status,
        }

    @classmethod
    def from_content(
        cls,
        content: bytes,
        *,
        tenant_id: str,
        format: str,
        display_name: str,
        source_id: str,
        created_at_ns: int,
        privacy_class: str = "synthetic",
    ) -> "RawObject":
        digest = sha256_hex(content)
        return cls(
            object_id=f"obj-{digest[:24]}",
            tenant_id=tenant_id,
            sha256=digest,
            byte_length=len(content),
            format=format,
            original_display_name=display_name,
            storage_key=f"objects/{digest[:2]}/{digest}",
            created_at_ns=created_at_ns,
            source_id=source_id,
            privacy_class=privacy_class,
            parser_status="pending",
        )


@dataclass(frozen=True)
class CapabilityField:
    """D.4 per-field-group capability entry."""

    field_group: str
    state: str
    reason: str = ""
    source_count: int = 0

    def __post_init__(self) -> None:
        if self.state not in CAPABILITY_STATES:
            raise CanonicalJSONError(f"unknown capability state {self.state!r}")

    def to_json(self) -> dict[str, Any]:
        return {
            "field_group": self.field_group,
            "state": self.state,
            "reason": self.reason,
            "source_count": self.source_count,
        }


@dataclass(frozen=True)
class CapabilityReport:
    """D.4 parser capability report for one session."""

    fields: tuple[CapabilityField, ...]

    def state_of(self, field_group: str) -> str:
        for f in self.fields:
            if f.field_group == field_group:
                return f.state
        return "not_applicable"

    def to_json(self) -> dict[str, Any]:
        return {"fields": [f.to_json() for f in self.fields]}


#: The F.1 extraction allowlist as a capability template. A source that
#: cannot provide a group reports it rather than letting the model invent it.
BASE_FIELD_GROUPS = (
    "packet_timing",
    "packet_lengths",
    "packet_counts",
    "ip_addresses",
    "transport_ports",
    "tcp_flags",
    "tcp_sequence",
    "tcp_window",
    "ip_ttl",
    "ip_fragmentation",
    "transport_payload_length",
    "flow_lifecycle",
)


def full_packet_capability(source_count: int = 1) -> CapabilityReport:
    """A fully observed packet telemetry source (synthetic fixture profile)."""
    return CapabilityReport(
        fields=tuple(
            CapabilityField(group, "observed", "", source_count)
            for group in BASE_FIELD_GROUPS
        )
    )


@dataclass
class QualityCounters:
    """D.4 ingestion quality counters with explicit denominators."""

    input_records: int = 0
    accepted_records: int = 0
    rejected_malformed: int = 0
    rejected_clock_invalid: int = 0
    duplicates_removed: int = 0
    conflicting_duplicates: int = 0
    unresolved_identities: int = 0
    truncated_packets: int = 0
    ambiguous_direction: int = 0
    missing_protocol_fields: int = 0
    excluded_late_arrivals: int = 0

    def accept(self) -> None:
        self.input_records += 1
        self.accepted_records += 1

    def reject(self, reason: str) -> None:
        self.input_records += 1
        attr = f"rejected_{reason}"
        if not hasattr(self, attr):
            attr = "rejected_malformed"
        setattr(self, attr, getattr(self, attr) + 1)

    @property
    def loss_rate(self) -> float:
        """Numerator/denominator loss, never a silent drop."""
        if self.input_records == 0:
            return 0.0
        return (self.input_records - self.accepted_records) / self.input_records

    def to_json(self) -> dict[str, Any]:
        payload = {
            key: getattr(self, key)
            for key in (
                "input_records",
                "accepted_records",
                "rejected_malformed",
                "rejected_clock_invalid",
                "duplicates_removed",
                "conflicting_duplicates",
                "unresolved_identities",
                "truncated_packets",
                "ambiguous_direction",
                "missing_protocol_fields",
                "excluded_late_arrivals",
            )
        }
        payload["loss_rate"] = self.loss_rate
        return payload
