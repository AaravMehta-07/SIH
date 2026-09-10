"""Event-stream normalization (Appendix D.3, D.4, F.1).

``normalize_events`` applies deduplication, clock validation and quality
counting to a raw event stream. The same external source ID with different
content is a conflict, not an ordinary duplicate (D.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.events import SecurityEvent
from ..contracts.objects import CapabilityReport, QualityCounters


@dataclass
class EventStream:
    """Ordered, deduplicated canonical events plus quality counters.

    Table-based sources (CSV profile, synthetic captures) carry a vectorized
    ``packet_table`` instead of materialized event objects; the two forms are
    never mixed for one session.
    """

    events: list[SecurityEvent]
    quality: QualityCounters
    capability: CapabilityReport
    packet_table: "np.ndarray | None" = None
    notes: dict | None = None

    def eligible(self, cutoff_ns: int) -> list[SecurityEvent]:
        return [e for e in self.events if e.eligible_at(cutoff_ns)]

    def sorted_by_source(self) -> list[SecurityEvent]:
        """E.2 canonical source ordering."""
        return sorted(
            self.events,
            key=lambda e: (
                e.ingested_at_ns,
                e.sensor_id,
                (e.source_sequence if e.source_sequence is not None else -1),
                e.event_id,
            ),
        )


@dataclass
class NormalizedSession:
    """Result of normalizing one source object (Appendix S ingest output)."""

    stream: EventStream
    object_id: str


def normalize_events(
    events: list[SecurityEvent],
    *,
    capability: CapabilityReport | None = None,
) -> EventStream:
    """Deduplicate by (sensor_id, source identity, payload fingerprint) and
    validate clocks; count every loss explicitly (D.4)."""
    quality = QualityCounters()
    seen: dict[tuple, SecurityEvent] = {}
    conflicts: set[tuple] = set()
    accepted: list[SecurityEvent] = []

    for event in events:
        quality.input_records += 1
        if (
            event.event_time_lower_ns > event.event_time_upper_ns
            or event.available_at_ns < event.event_time_lower_ns - 5 * 60 * 1_000_000_000
        ):
            quality.reject("clock_invalid")
            continue
        if not event.validity:
            quality.reject("malformed")
            continue
        fingerprint = (
            event.sensor_id,
            event.source_sequence,
            event.event_kind,
            event.event_time_upper_ns,
            id_key(event),
        )
        prior = seen.get(fingerprint)
        if prior is not None:
            if prior.raw_object_hash and (
                prior.raw_object_hash != event.raw_object_hash
            ):
                # D.3: same source identity, different content -> conflict
                conflicts.add(fingerprint)
                quality.conflicting_duplicates += 1
                continue
            quality.duplicates_removed += 1
            continue
        seen[fingerprint] = event
        accepted.append(event)
        quality.accepted_records += 1

    return EventStream(
        events=accepted,
        quality=quality,
        capability=capability or CapabilityReport(fields=()),
    )


def id_key(event: SecurityEvent) -> str:
    """Payload fingerprint component for dedup identity (D.3)."""
    if isinstance(event.observables, object) and hasattr(
        event.observables, "src_address"
    ):
        obs = event.observables
        return f"{obs.src_address}:{obs.src_port}->{obs.dst_address}:{obs.dst_port}"
    return str(sorted(event.observables.items()))
