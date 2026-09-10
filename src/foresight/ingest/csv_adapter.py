"""Versioned CSV adapter profiles (Build Spec F.4).

Named versioned mappings, not a universal guesser. A profile specifies
columns, units, direction, identity fields, flow times, availability
convention and label columns that must be quarantined. A CSV without packet
measurements runs as a degraded input: flow values are kept, packet-level
feature groups report ``not_available`` in the capability report (D.4) and
the corresponding validity bits stay zero.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from ..contracts.objects import (
    CapabilityField,
    CapabilityReport,
    QualityCounters,
    RawObject,
)
from .normalizer import EventStream
from .synthetic import PROTO_MAP, PROTO_TCP, PROTO_UDP, finalize_table

_NS = 1_000_000_000


@dataclass(frozen=True)
class CsvProfile:
    """F.4 profile: exact column names, units and conventions."""

    profile_id: str
    columns: dict[str, str]  # logical name -> CSV column
    timestamp_unit: str = "s"  # "s" | "ms" | "ns"
    flow_export_delay_ns: int = 2 * _NS  # availability convention
    label_columns: tuple[str, ...] = ()  # quarantined from model inputs


#: v1 flow-CSV profile. Label columns are stored only in the label/evaluator
#: process (F.4); the model input builder never reads them.
FLOW_CSV_V1 = CsvProfile(
    profile_id="flow-csv-v1",
    columns={
        "start": "flow_start",
        "end": "flow_end",
        "src": "src_addr",
        "dst": "dst_addr",
        "sport": "src_port",
        "dport": "dst_port",
        "proto": "protocol",
        "bytes": "bytes",
        "packets": "packets",
        "duration": "duration_s",
    },
    label_columns=("label", "attack_name", "scenario_id"),
)

FLOW_CSV_V1_NAMES = frozenset(FLOW_CSV_V1.columns.values()) | set(
    FLOW_CSV_V1.label_columns
)


def _unit_to_ns(value: str, unit: str) -> int:
    number = float(value)
    if unit == "ns":
        return int(number)
    if unit == "ms":
        return int(number * 1_000_000)
    return int(number * _NS)


def parse_flow_csv(
    path: Path,
    *,
    profile: CsvProfile = FLOW_CSV_V1,
    resolve=None,
    max_rows: int = 2_000_000,
) -> EventStream:
    """Parse a flow CSV into the internal packet-table stream.

    Each flow row becomes one table row (aggregate view): packet-derived
    fields are masked, per-flow bytes/packets feed the flow-capable feature
    groups. The capability report states exactly which groups are available
    (D.4) — the model never invents packet fields (Section 9).
    """
    quality = QualityCounters()
    rows: list[tuple] = []
    hosts: list[str] = []
    host_index: dict[str, int] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        if len(header) != len(set(header)):
            raise ValueError("duplicate column names are an error (F.4)")
        unknown = [c for c in header if c not in FLOW_CSV_V1_NAMES]
        for row in reader:
            if len(rows) >= max_rows:
                quality.reject("malformed")  # quota bound
                continue
            try:
                start = _unit_to_ns(row[profile.columns["start"]], profile.timestamp_unit)
                end = _unit_to_ns(row[profile.columns["end"]], profile.timestamp_unit)
                total_bytes = int(row[profile.columns["bytes"]])
                packet_count = int(row[profile.columns["packets"]])
            except (KeyError, ValueError, TypeError):
                quality.reject("malformed")
                continue
            if total_bytes < 0 or packet_count < 0 or end < start:
                quality.reject("malformed")  # impossible negative durations (F.4)
                continue
            proto_name = (row.get(profile.columns["proto"]) or "tcp").lower()
            proto = PROTO_MAP.get(proto_name, 2)
            sport = int(row.get(profile.columns["sport"]) or -1)
            dport = int(row.get(profile.columns["dport"]) or -1)
            src_addr = row[profile.columns["src"]]
            dst_addr = row[profile.columns["dst"]]
            # Host registry: distinct addresses become table host indices;
            # ``resolve`` optionally maps an address to a stable entity name.
            for addr in (src_addr, dst_addr):
                if addr not in host_index:
                    host_index[addr] = len(hosts)
                    hosts.append(resolve(addr) if resolve else f"addr:{addr}")
            src_idx = host_index[src_addr]
            dst_idx = host_index[dst_addr]
            # Availability: closed-flow totals exist only at end + export delay
            # (F.2); the row's availability clock respects that, never the
            # flow start (TM04).
            available = end + profile.flow_export_delay_ns
            rows.append(
                (
                    start,
                    available,
                    available + 1_000_000,
                    src_idx,
                    dst_idx,
                    sport,
                    dport,
                    proto,
                    0,
                    total_bytes,
                    -1,  # packet payload length not observable from a flow row
                    -1,
                    -1,
                    -1,
                    0,
                )
            )
            quality.accept()

    capability = CapabilityReport(
        fields=(
            CapabilityField("packet_timing", "not_available",
                            "flow CSV has no per-packet timestamps"),
            CapabilityField("packet_lengths", "not_available",
                            "flow CSV has no per-packet lengths"),
            CapabilityField("tcp_flags", "not_available",
                            "flow CSV has no flag columns in flow-csv-v1"),
            CapabilityField("tcp_sequence", "not_available", "no sequence data"),
            CapabilityField("tcp_window", "not_available", "no window data"),
            CapabilityField("ip_ttl", "not_available", "no TTL data"),
            CapabilityField("transport_payload_length", "not_available",
                            "payload length not in flow CSV"),
            CapabilityField("flow_lifecycle", "derived",
                            "flow start/end/packets/bytes from export"),
            CapabilityField("ip_addresses", "observed"),
            CapabilityField("transport_ports", "observed"),
        )
    )
    unknown_report = {
        "unknown_columns_excluded": unknown,
        "hosts": hosts,
    }
    stream = EventStream(
        events=[],  # table-based sessions carry packets, not event objects
        quality=quality,
        capability=capability,
        packet_table=finalize_table(rows),
        notes=unknown_report,
    )
    return stream
