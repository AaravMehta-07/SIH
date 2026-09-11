"""Bounded subprocess PCAP ingestion (F.1, L.1, Appendix Q)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from ..contracts.events import EntityRef, PacketObservables, SecurityEvent
from ..contracts.objects import CapabilityField, CapabilityReport, QualityCounters
from .normalizer import EventStream


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def parse_pcap(
    path: Path,
    *,
    max_bytes: int = 512 * 1024 * 1024,
    max_packets: int = 5_000_000,
    max_captured_packet_bytes: int = 262_144,
    timeout_seconds: int = 180,
) -> EventStream:
    """Extract packet headers without payload retention or shell expansion."""

    source = Path(path).resolve(strict=True)
    if source.stat().st_size > max_bytes:
        raise ValueError("PCAP exceeds configured byte quota")
    worker = Path(__file__).with_name("pcap_worker.py")
    with tempfile.TemporaryDirectory(prefix="foresight-pcap-") as temp:
        table_path = Path(temp) / "packets.npy"
        summary_path = Path(temp) / "summary.json"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(worker),
                str(source),
                str(table_path),
                str(summary_path),
                str(max_packets),
                str(max_captured_packet_bytes),
            ],
            shell=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            creationflags=creationflags,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "worker failed")[-1000:]
            raise ValueError(f"isolated PCAP parser rejected input: {detail}")
        from .pcap_worker import DTYPE

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        table = np.fromfile(table_path, dtype=DTYPE)
        if int(summary["counters"].get("out_of_order_records", 0)):
            table = table[np.lexsort((table["ingested_ns"], table["t_ns"]))]
    raw = summary["counters"]
    quality = QualityCounters(
        input_records=int(raw["input_records"]),
        accepted_records=int(raw["accepted_records"]),
        rejected_malformed=int(raw["rejected_malformed"]),
        truncated_packets=int(raw["truncated_packets"]),
    )
    observed = int(quality.accepted_records)
    capability = CapabilityReport(
        fields=(
            CapabilityField("packet_timing", "observed", source_count=observed),
            CapabilityField("packet_lengths", "observed", source_count=observed),
            CapabilityField("packet_counts", "observed", source_count=observed),
            CapabilityField("ip_addresses", "observed", source_count=observed),
            CapabilityField("transport_ports", "observed", source_count=observed),
            CapabilityField("tcp_flags", "observed", source_count=observed),
            CapabilityField("tcp_sequence", "observed", source_count=observed),
            CapabilityField("tcp_window", "observed", source_count=observed),
            CapabilityField("ip_ttl", "observed", source_count=observed),
            CapabilityField("ip_fragmentation", "observed", source_count=observed),
            CapabilityField("transport_payload_length", "derived",
                            "derived from captured IP/transport headers", observed),
            CapabilityField("flow_lifecycle", "derived",
                            "directional segments derived with fixed idle/active timeouts", observed),
            CapabilityField("independent_availability_clock", "not_available",
                            "offline replay uses capture timestamp as receipt time"),
        )
    )
    return EventStream(
        events=[],
        quality=quality,
        capability=capability,
        packet_table=table,
        notes={
            "adapter": "pcap-ipv4-v1",
            "source_sha256": _hash(source),
            "hosts": [f"addr:{value}" for value in summary["hosts"]],
            "unsupported_link_records": int(raw["unsupported_link_records"]),
            "out_of_order_records": int(raw.get("out_of_order_records", 0)),
            "payload_retained": False,
            "parser_isolation": "subprocess -I, shell=False, byte/packet/time bounds",
            "clock_model": "capture timestamp; no independent receipt clock",
        },
    )


def pcap_event_at(stream: EventStream, packet_index: int, *, source_hash: str | None = None
                  ) -> SecurityEvent:
    """Materialize one typed canonical packet event for evidence/replay."""

    if stream.packet_table is None or not 0 <= packet_index < len(stream.packet_table):
        raise IndexError(packet_index)
    row = stream.packet_table[packet_index]
    hosts = stream.notes["hosts"]
    src = hosts[int(row["src"])].removeprefix("addr:")
    dst = hosts[int(row["dst"])].removeprefix("addr:")
    proto = ("tcp", "udp", "other")[int(row["proto"])]
    flags = int(row["flags"])
    obs = PacketObservables(
        src_address=src,
        dst_address=dst,
        protocol=proto,
        src_port=None if int(row["sport"]) < 0 else int(row["sport"]),
        dst_port=None if int(row["dport"]) < 0 else int(row["dport"]),
        captured_length=int(row["captured_len"]),
        wire_length=int(row["wire_len"]),
        transport_payload_length=(None if int(row["payload_len"]) < 0 else int(row["payload_len"])),
        tcp_flags=tuple(bool(flags & (1 << bit)) for bit in range(6)),
        tcp_sequence=None if int(row["tcp_seq"]) < 0 else int(row["tcp_seq"]),
        tcp_window=None if int(row["tcp_window"]) < 0 else int(row["tcp_window"]),
        ip_ttl=None if int(row["ttl"]) < 0 else int(row["ttl"]),
        ip_fragmented=bool(row["fragmented"]),
    )
    at = int(row["t_ns"])
    refs = tuple(
        EntityRef("ctu13-public", f"addr:{address}", "address", valid_from_ns=at)
        for address in (src, dst)
    )
    digest = source_hash or str(stream.notes.get("source_sha256", ""))
    return SecurityEvent(
        tenant_id="ctu13-public",
        event_id=f"pcap-{digest[:12]}-{packet_index + 1}",
        sensor_id="offline-pcap",
        source_type="pcap",
        source_sequence=packet_index + 1,
        parser_hash="pcap-ipv4-v1",
        event_time_lower_ns=at,
        event_time_upper_ns=at,
        available_at_ns=int(row["available_ns"]),
        ingested_at_ns=int(row["ingested_ns"]),
        event_kind="packet_observed",
        observables=obs,
        subjects=(refs[0],),
        objects=(refs[1],),
        raw_object_hash=digest,
        raw_pointer={"kind": "pcap_packet", "packet_number": packet_index + 1},
        evidence_group_id=f"pcap-{digest[:12]}-{packet_index + 1}",
        privacy_class="approved_public",
    )
