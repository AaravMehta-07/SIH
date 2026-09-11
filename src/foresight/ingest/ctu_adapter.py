"""Qualified CTU-13 bidirectional-flow adapter (Sections 6-9, M.1).

The adapter is deliberately dataset-specific.  CTU ``binetflow`` rows are
completed bidirectional flow summaries, not packets.  Packet-only fields are
therefore reported unavailable and never synthesized.  Labels travel in a
separate evaluator-side table: ``Background`` is never a benign negative and
only ``From-Normal`` is eligible for the verified-normal class.
"""

from __future__ import annotations

import csv
import hashlib
import ipaddress
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import numpy as np

from ..contracts.events import EntityRef, FlowObservables, SecurityEvent
from ..contracts.objects import CapabilityField, CapabilityReport, QualityCounters
from ..ingest.normalizer import EventStream
from ..ingest.synthetic import PROTO_MAP, finalize_table

_NS = 1_000_000_000
_CTU_TZ = ZoneInfo("Europe/Prague")
_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_HEADER = (
    "StartTime", "Dur", "Proto", "SrcAddr", "Sport", "Dir", "DstAddr",
    "Dport", "State", "sTos", "dTos", "TotPkts", "TotBytes", "SrcBytes",
    "Label",
)
_C2_MARKERS = ("-cc", "-c&c", "-irc", "command-and-control")


@dataclass(frozen=True)
class CtuLabel:
    """Evaluator-only CTU label; never included in model feature rows."""

    row_number: int
    category: str  # botnet | normal | background | unresolved
    raw_label: str
    entity_id: str
    event_time_ns: int
    task_indices: tuple[int, ...]
    mapping_reason: str


@dataclass(frozen=True)
class CtuParseResult:
    stream: EventStream
    labels: tuple[CtuLabel, ...]
    source_sha256: str
    scenario_id: str


def _sha256_file(path: Path, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp_ns(value: str) -> int:
    # CTU README timelines identify the local zone as CEST.  ZoneInfo keeps
    # the conversion explicit and rejects no precision from the source text.
    dt = datetime.strptime(value.strip(), "%Y/%m/%d %H:%M:%S.%f").replace(
        tzinfo=_CTU_TZ
    )
    delta = dt.astimezone(timezone.utc) - _UNIX_EPOCH
    return ((delta.days * 86_400 + delta.seconds) * _NS) + delta.microseconds * 1_000


def _port(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    parsed = int(value, 0)
    if not 0 <= parsed <= 65535:
        raise ValueError("port outside [0, 65535]")
    return parsed


def classify_ctu_label(raw: str) -> tuple[str, tuple[int, ...], str]:
    """Conservative T.4 mapping of one CTU flow label.

    Only source-authored normal labels are benign.  ``To-Normal`` and
    ``To-Botnet`` are explicitly called non-attributable by the scenario
    documentation.  Botnet rows map to task 3 only when the label itself
    carries a C2 marker; generic malware traffic does not invent C2 truth.
    """

    label = raw.strip()
    lower = label.lower()
    if lower.startswith("flow=from-normal"):
        return "normal", (), "source label From-Normal; verified benign class"
    if lower.startswith("flow=background"):
        return "background", (), "CTU Background retained as a separate class"
    if lower.startswith("flow=from-botnet"):
        if any(marker in lower for marker in _C2_MARKERS):
            return "botnet", (0, 3), (
                "From-Botnet supports malicious-contact proxy; source label also "
                "identifies C2/IRC traffic"
            )
        return "botnet", (0,), "From-Botnet supports malicious-contact proxy only"
    return "unresolved", (), "directional attribution is not established"


def _address_ref(address: str, *, scenario_id: str, at_ns: int) -> EntityRef:
    # IP is intentionally represented as an address identity, never a device.
    ipaddress.ip_address(address)
    return EntityRef(
        tenant_id="ctu13-public",
        entity_id=f"addr:{address}",
        entity_type="address",
        valid_from_ns=at_ns,
        link_confidence=1.0,
        source_refs=(scenario_id,),
    )


def _parse_row(row: dict[str, str], row_number: int, scenario_id: str):
    start_ns = _timestamp_ns(row["StartTime"])
    try:
        duration_ns = int((Decimal(row["Dur"].strip()) * _NS).to_integral_value())
    except InvalidOperation as exc:
        raise ValueError("invalid duration") from exc
    if duration_ns < 0:
        raise ValueError("negative duration")
    end_ns = start_ns + duration_ns
    src = row["SrcAddr"].strip()
    dst = row["DstAddr"].strip()
    ipaddress.ip_address(src)
    ipaddress.ip_address(dst)
    proto_name = row["Proto"].strip().lower()
    proto = proto_name if proto_name in ("tcp", "udp") else "other"
    packets = int(row["TotPkts"])
    total_bytes = int(row["TotBytes"])
    src_bytes = int(row["SrcBytes"])
    if packets < 0 or total_bytes < 0 or not 0 <= src_bytes <= total_bytes:
        raise ValueError("invalid flow counts")
    obs = FlowObservables(
        src_address=src,
        dst_address=dst,
        protocol=proto,
        src_port=_port(row["Sport"]),
        dst_port=_port(row["Dport"]),
        direction=row["Dir"].strip(),
        duration_ns=duration_ns,
        total_packets=packets,
        total_bytes=total_bytes,
        src_bytes=src_bytes,
        dst_bytes=total_bytes - src_bytes,
    )
    category, task_indices, reason = classify_ctu_label(row["Label"])
    event = SecurityEvent(
        tenant_id="ctu13-public",
        event_id=f"ctu13-{scenario_id}-row-{row_number}",
        sensor_id=f"ctu13-{scenario_id}-argus",
        source_type="ctu13-binetflow",
        source_sequence=row_number - 1,
        ingest_sequence=row_number - 1,
        parser_hash="ctu13-binetflow-v1",
        event_time_lower_ns=start_ns,
        event_time_upper_ns=end_ns,
        # CTU has no independent export/receipt clocks.  The replay profile
        # conservatively makes closed-flow fields eligible at flow closure.
        available_at_ns=end_ns,
        ingested_at_ns=end_ns,
        event_kind="flow_segment_closed",
        observables=obs,
        subjects=(_address_ref(src, scenario_id=scenario_id, at_ns=start_ns),),
        objects=(_address_ref(dst, scenario_id=scenario_id, at_ns=start_ns),),
        validity=True,
        provenance_verified=True,
        raw_pointer={"kind": "csv_row", "row_number": row_number,
                     "columns": list(_HEADER)},
        evidence_group_id=f"ctu13-{scenario_id}-row-{row_number}",
        privacy_class="approved_public",
        retention_class="dataset-license",
    )
    label = CtuLabel(
        row_number=row_number,
        category=category,
        raw_label=row["Label"].strip(),
        entity_id=f"addr:{src}",
        event_time_ns=end_ns,
        task_indices=task_indices,
        mapping_reason=reason,
    )
    return event, label


def iter_ctu_events(path: Path, *, scenario_id: str, max_rows: int = 2_000_000
                    ) -> Iterator[tuple[SecurityEvent, CtuLabel]]:
    """Stream canonical events without retaining millions of objects."""

    csv.field_size_limit(1 << 20)
    with path.open("r", newline="", encoding="utf-8-sig", errors="strict") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != _HEADER:
            raise ValueError("CTU binetflow header does not match profile v1")
        for index, row in enumerate(reader, start=2):
            if index - 1 > max_rows:
                raise ValueError(f"row quota exceeded ({max_rows})")
            yield _parse_row(row, index, scenario_id)


def parse_ctu_binetflow(
    path: Path,
    *,
    scenario_id: str,
    max_rows: int = 5_000_000,
    max_bytes: int = 1_500_000_000,
    materialize_events: bool = False,
) -> CtuParseResult:
    """Parse a qualified CTU file into model rows and quarantined labels.

    ``materialize_events`` is intended for fixtures/evidence export.  The
    default keeps the large real corpus memory-lean while ``iter_ctu_events``
    remains the canonical streaming boundary.
    """

    path = Path(path)
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(f"input exceeds byte quota ({size} > {max_bytes})")
    quality = QualityCounters()
    events: list[SecurityEvent] = []
    label_summaries: dict[tuple[str, int], CtuLabel] = {}
    label_counts: dict[str, int] = {
        name: 0 for name in ("normal", "botnet", "background", "unresolved")
    }
    row_buffer: list[tuple] = []
    row_chunks: list[np.ndarray] = []
    hosts: list[str] = []
    host_index: dict[str, int] = {}

    csv.field_size_limit(1 << 20)
    with path.open("r", newline="", encoding="utf-8-sig", errors="strict") as handle:
        reader = csv.DictReader(handle)
        header = tuple(reader.fieldnames or ())
        if len(header) != len(set(header)):
            raise ValueError("duplicate column names are an error (F.4/Q)")
        if header != _HEADER:
            raise ValueError("CTU binetflow header does not match profile v1")
        for index, row in enumerate(reader, start=2):
            if quality.input_records >= max_rows:
                raise ValueError(f"row quota exceeded ({max_rows})")
            try:
                event, label = _parse_row(row, index, scenario_id)
            except (KeyError, TypeError, ValueError, OverflowError):
                quality.reject("malformed")
                continue
            obs = event.observables
            assert isinstance(obs, FlowObservables)
            for address in (obs.src_address, obs.dst_address):
                if address not in host_index:
                    host_index[address] = len(hosts)
                    hosts.append(f"addr:{address}")
            # One completed-flow observation is placed at closure.  Totals
            # remain flow aggregates: payload/header/flag fields use -1/0 and
            # are masked by the capability report downstream.
            row_buffer.append(
                (
                    event.event_time_lower_ns,
                    event.available_at_ns,
                    event.ingested_at_ns,
                    host_index[obs.src_address],
                    host_index[obs.dst_address],
                    -1 if obs.src_port is None else obs.src_port,
                    -1 if obs.dst_port is None else obs.dst_port,
                    PROTO_MAP.get(obs.protocol, 2),
                    0,
                    obs.total_bytes,
                    -1,
                    -1,
                    -1,
                    -1,
                    0,
                )
            )
            if materialize_events:
                events.append(event)
            label_counts[label.category] += 1
            if label.category == "normal":
                label_summaries.setdefault((label.entity_id, -1), label)
            elif label.category == "botnet":
                for task_index in label.task_indices:
                    key = (label.entity_id, task_index)
                    prior = label_summaries.get(key)
                    if prior is None or label.event_time_ns < prior.event_time_ns:
                        label_summaries[key] = CtuLabel(
                            row_number=label.row_number,
                            category=label.category,
                            raw_label=label.raw_label,
                            entity_id=label.entity_id,
                            event_time_ns=label.event_time_ns,
                            task_indices=(task_index,),
                            mapping_reason=label.mapping_reason,
                        )
            quality.accept()
            if len(row_buffer) >= 65_536:
                row_chunks.append(finalize_table(row_buffer))
                row_buffer.clear()

    if row_buffer:
        row_chunks.append(finalize_table(row_buffer))
    if row_chunks:
        packet_table = np.concatenate(row_chunks)
        order = np.lexsort((packet_table["ingested_ns"], packet_table["t_ns"]))
        packet_table = packet_table[order]
    else:
        packet_table = finalize_table([])

    capability = CapabilityReport(
        fields=(
            CapabilityField("flow_lifecycle", "observed", "start, duration and closure"),
            CapabilityField("flow_start_time", "observed", "StartTime field"),
            CapabilityField("flow_total_packets", "observed", "bidirectional total only"),
            CapabilityField("flow_total_bytes", "observed", "total and source bytes"),
            CapabilityField("ip_addresses", "observed"),
            CapabilityField("transport_ports", "observed"),
            CapabilityField("transport_protocol", "observed"),
            CapabilityField("packet_timing", "not_available", "no packet timestamps"),
            CapabilityField("packet_lengths", "not_available", "flow totals are not packet lengths"),
            CapabilityField("packet_counts", "not_available",
                            "only bidirectional per-flow totals; no directional packet allocation"),
            CapabilityField("tcp_flags", "not_available", "Argus state is not packet flag telemetry"),
            CapabilityField("tcp_sequence", "not_available", "not present in binetflow"),
            CapabilityField("tcp_window", "not_available", "not present in binetflow"),
            CapabilityField("ip_ttl", "not_available", "not present in binetflow"),
            CapabilityField("ip_fragmentation", "not_available", "not present in binetflow"),
            CapabilityField("transport_payload_length", "not_available", "not present in binetflow"),
            CapabilityField("independent_availability_clock", "not_available",
                            "replay uses flow closure; CTU publishes no collector receipt clock"),
        )
    )
    return CtuParseResult(
        stream=EventStream(
            events=events,
            quality=quality,
            capability=capability,
            packet_table=packet_table,
            notes={
                "adapter": "ctu13-binetflow-v1",
                "scenario_id": scenario_id,
                "hosts": hosts,
                "labels_quarantined": True,
                "label_counts": label_counts,
                "background_is_benign": False,
                "clock_model": "event interval from StartTime+Dur; availability/ingestion replayed at closure",
                "canonical_events_materialized": materialize_events,
            },
        ),
        labels=tuple(
            sorted(label_summaries.values(), key=lambda item: item.event_time_ns)
        ),
        source_sha256=_sha256_file(path),
        scenario_id=scenario_id,
    )
