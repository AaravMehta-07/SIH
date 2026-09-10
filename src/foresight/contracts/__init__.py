"""Typed wire and storage contracts (Build Spec Appendices D.1-D.4, E.2).

Every record that crosses a module or process boundary is a typed dataclass
here. JSON produced from these records is canonical (E.2): deterministic key
order, UTF-8, decimal-string nanosecond timestamps, no nonfinite numbers.
"""

from .canonical import (
    CanonicalJSONError,
    canonical_json,
    decimal_ns,
    parse_decimal_ns,
    sha256_hex,
    validate_opaque_id,
)
from .events import (
    ENTITY_TYPES,
    EVENT_KINDS,
    SCHEMA as SECURITY_EVENT_SCHEMA,
    EntityRef,
    PacketObservables,
    SecurityEvent,
    SupersedeError,
    build_event,
)
from .objects import (
    FORMATS,
    PARSER_STATUSES,
    PRIVACY_CLASSES,
    CapabilityField,
    CapabilityReport,
    QualityCounters,
    RawObject,
)
from .quality import HealthState, SupportStatus

__all__ = [
    "CanonicalJSONError",
    "canonical_json",
    "decimal_ns",
    "parse_decimal_ns",
    "sha256_hex",
    "validate_opaque_id",
    "ENTITY_TYPES",
    "EVENT_KINDS",
    "SECURITY_EVENT_SCHEMA",
    "EntityRef",
    "PacketObservables",
    "SecurityEvent",
    "SupersedeError",
    "build_event",
    "FORMATS",
    "PARSER_STATUSES",
    "PRIVACY_CLASSES",
    "CapabilityField",
    "CapabilityReport",
    "QualityCounters",
    "RawObject",
    "HealthState",
    "SupportStatus",
]
