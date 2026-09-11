import struct
from pathlib import Path

from foresight.ingest.pcap_adapter import parse_pcap, pcap_event_at


def _tiny_pcap(path: Path) -> None:
    ethernet = bytes.fromhex("00112233445566778899aabb0800")
    ipv4 = bytes.fromhex("4500002812344000400600000a0000010a000002")
    tcp = struct.pack("!HHIIBBHHH", 12345, 443, 99, 0, 5 << 4, 0x02, 64240, 0, 0)
    packet = ethernet + ipv4 + tcp
    global_header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    record = struct.pack("<IIII", 1_600_000_000, 123456, len(packet), len(packet)) + packet
    path.write_bytes(global_header + record)


def test_pcap_adapter_is_bounded_and_typed(tmp_path: Path):
    path = tmp_path / "one.pcap"
    _tiny_pcap(path)
    stream = parse_pcap(path, timeout_seconds=30)
    assert stream.quality.accepted_records == 1
    assert stream.capability.state_of("tcp_flags") == "observed"
    assert stream.notes["payload_retained"] is False
    event = pcap_event_at(stream, 0)
    assert event.observables.src_address == "10.0.0.1"
    assert event.observables.flag_bits["syn"] is True
    assert event.raw_pointer == {"kind": "pcap_packet", "packet_number": 1}


def test_pcap_adapter_rejects_truncated_input(tmp_path: Path):
    path = tmp_path / "bad.pcap"
    path.write_bytes(b"not a pcap")
    try:
        parse_pcap(path, timeout_seconds=30)
    except ValueError as exc:
        assert "rejected" in str(exc)
    else:
        raise AssertionError("truncated input must be rejected")
