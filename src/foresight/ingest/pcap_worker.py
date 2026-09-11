"""Isolated, bounded classic-PCAP extractor used by :mod:`pcap_adapter`.

This module intentionally has no project imports.  It accepts fixed positional
arguments from the parent, reads one file sequentially, and writes a NumPy
table plus a small JSON summary.  Packet payload bytes are never retained.
"""

from __future__ import annotations

import ipaddress
import json
import struct
import sys
from pathlib import Path

import numpy as np


DTYPE = np.dtype(
    [
        ("t_ns", "<i8"), ("available_ns", "<i8"), ("ingested_ns", "<i8"),
        ("src", "<i4"), ("dst", "<i4"), ("sport", "<i4"), ("dport", "<i4"),
        ("proto", "i1"), ("flags", "u1"), ("captured_len", "<i4"),
        ("wire_len", "<i4"),
        ("payload_len", "<i4"), ("ttl", "<i2"), ("tcp_window", "<i4"),
        ("tcp_seq", "<i8"), ("fragmented", "u1"),
    ]
)


def _decode_packet(data: bytes, wire_len: int):
    if len(data) < 14:
        raise ValueError("truncated ethernet header")
    ether_type = struct.unpack("!H", data[12:14])[0]
    offset = 14
    if ether_type in (0x8100, 0x88A8):
        if len(data) < 18:
            raise ValueError("truncated vlan header")
        ether_type = struct.unpack("!H", data[16:18])[0]
        offset = 18
    if ether_type != 0x0800:
        return None  # v1 capability is IPv4 only; count as unsupported, not bad.
    if len(data) < offset + 20:
        raise ValueError("truncated ipv4 header")
    first = data[offset]
    version, ihl = first >> 4, (first & 0x0F) * 4
    if version != 4 or ihl < 20 or len(data) < offset + ihl:
        raise ValueError("invalid ipv4 header")
    total_len = struct.unpack("!H", data[offset + 2:offset + 4])[0]
    if total_len < ihl:
        raise ValueError("invalid ipv4 total length")
    protocol = data[offset + 9]
    ttl = data[offset + 8]
    frag = struct.unpack("!H", data[offset + 6:offset + 8])[0]
    fragmented = bool((frag & 0x1FFF) or (frag & 0x2000))
    src = str(ipaddress.ip_address(data[offset + 12:offset + 16]))
    dst = str(ipaddress.ip_address(data[offset + 16:offset + 20]))
    transport = offset + ihl
    captured_ip_end = min(len(data), offset + total_len)
    capture_truncated = captured_ip_end < offset + total_len
    sport = dport = -1
    flags = 0
    seq = -1
    window = -1
    payload_len = -1
    proto_code = 2
    if protocol == 6:
        proto_code = 0
        if captured_ip_end < transport + 20:
            raise ValueError("truncated tcp header")
        sport, dport = struct.unpack("!HH", data[transport:transport + 4])
        seq = struct.unpack("!I", data[transport + 4:transport + 8])[0]
        tcp_hlen = (data[transport + 12] >> 4) * 4
        if tcp_hlen < 20 or captured_ip_end < transport + tcp_hlen:
            raise ValueError("invalid tcp header length")
        raw_flags = data[transport + 13]
        # PCAP bits FIN,SYN,RST,PSH,ACK,URG -> FORESIGHT SYN,ACK,FIN,RST,PSH,URG.
        flags = ((raw_flags >> 1) & 1) | (((raw_flags >> 4) & 1) << 1)
        flags |= (raw_flags & 1) << 2
        flags |= ((raw_flags >> 2) & 1) << 3
        flags |= ((raw_flags >> 3) & 1) << 4
        flags |= ((raw_flags >> 5) & 1) << 5
        window = struct.unpack("!H", data[transport + 14:transport + 16])[0]
        payload_len = max(0, total_len - ihl - tcp_hlen)
    elif protocol == 17:
        proto_code = 1
        if captured_ip_end < transport + 8:
            raise ValueError("truncated udp header")
        sport, dport, udp_len = struct.unpack("!HHH", data[transport:transport + 6])
        if udp_len < 8:
            raise ValueError("invalid udp length")
        payload_len = max(0, min(udp_len, total_len - ihl) - 8)
    if capture_truncated:
        payload_len = -1
    return (
        src, dst, sport, dport, proto_code, flags, wire_len, payload_len,
        ttl, window, seq, int(fragmented), capture_truncated,
    )


def main() -> int:
    if len(sys.argv) != 6:
        return 64
    source = Path(sys.argv[1])
    table_path = Path(sys.argv[2])
    summary_path = Path(sys.argv[3])
    max_packets = int(sys.argv[4])
    max_capture = int(sys.argv[5])
    rows = []
    chunk_rows = 65_536
    hosts = []
    host_index = {}
    counters = {"input_records": 0, "accepted_records": 0,
                "rejected_malformed": 0, "truncated_packets": 0,
                "unsupported_link_records": 0, "out_of_order_records": 0}
    previous_t_ns = None
    table_path.unlink(missing_ok=True)
    with source.open("rb") as handle:
        header = handle.read(24)
        if len(header) != 24:
            raise ValueError("truncated pcap global header")
        magic = header[:4]
        formats = {
            b"\xd4\xc3\xb2\xa1": ("<", 1_000),
            b"\xa1\xb2\xc3\xd4": (">", 1_000),
            b"\x4d\x3c\xb2\xa1": ("<", 1),
            b"\xa1\xb2\x3c\x4d": (">", 1),
        }
        if magic not in formats:
            raise ValueError("unsupported capture format; classic PCAP required")
        endian, fraction_scale = formats[magic]
        _major, _minor, _zone, _sigfigs, snaplen, network = struct.unpack(
            endian + "HHiiii", header[4:24]
        )
        if network != 1:
            raise ValueError(f"unsupported pcap link type {network}; Ethernet required")
        packet_header = struct.Struct(endian + "IIII")
        packet_number = 0
        while True:
            raw = handle.read(16)
            if not raw:
                break
            counters["input_records"] += 1
            packet_number += 1
            if packet_number > max_packets:
                raise ValueError(f"packet quota exceeded ({max_packets})")
            if len(raw) != 16:
                counters["rejected_malformed"] += 1
                counters["truncated_packets"] += 1
                break
            sec, fraction, captured_len, wire_len = packet_header.unpack(raw)
            if captured_len > max_capture or captured_len > snaplen:
                raise ValueError("captured packet length exceeds configured bounds")
            data = handle.read(captured_len)
            if len(data) != captured_len:
                counters["rejected_malformed"] += 1
                counters["truncated_packets"] += 1
                break
            try:
                decoded = _decode_packet(data, wire_len)
            except ValueError:
                counters["rejected_malformed"] += 1
                continue
            if decoded is None:
                counters["unsupported_link_records"] += 1
                continue
            src, dst, *values = decoded
            capture_truncated = bool(values.pop())
            if capture_truncated:
                counters["truncated_packets"] += 1
            for address in (src, dst):
                if address not in host_index:
                    host_index[address] = len(hosts)
                    hosts.append(address)
            t_ns = sec * 1_000_000_000 + fraction * fraction_scale
            if previous_t_ns is not None and t_ns < previous_t_ns:
                counters["out_of_order_records"] += 1
            previous_t_ns = t_ns
            rows.append((t_ns, t_ns, t_ns, host_index[src], host_index[dst],
                         values[0], values[1], values[2], values[3], captured_len,
                         *values[4:]))
            counters["accepted_records"] += 1
            if len(rows) >= chunk_rows:
                np.asarray(rows, dtype=DTYPE).tofile(table_path)
                rows.clear()
    if rows:
        np.asarray(rows, dtype=DTYPE).tofile(table_path)
    elif not table_path.exists():
        table_path.touch()
    summary_path.write_text(
        json.dumps({"counters": counters, "hosts": hosts, "parser": "pcap-ipv4-v1"}),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
