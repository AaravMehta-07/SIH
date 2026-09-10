"""Synthetic packet-telemetry capture generator (Build Spec C.4, Section 6).

Produces **disclosed synthetic** captures at packet granularity: a numpy
packet table (fast, prefix-safe) plus ground-truth label manifests for the
five Section-11 targets. This is the corpus generator behind the offline
training/evaluation pipeline and the console demo sessions; every artifact
carries ``privacy_class: synthetic`` and no measured-performance claim.

Attack stages are engineered to carry the real traffic signatures the feature
registry measures (F.6/F.7), so the world model learns hazard from legal
features rather than a scripted shortcut:

- port scan      -> unique_destination_port_count, destination_port_entropy,
                    contiguous_port_coverage, ordered_port_arrival_score,
                    failed_connection_fraction (SYN sweep, sequential ports)
- C2 beaconing   -> iat_mean/iat_variance (low jitter), fixed payload sizes
- lateral move   -> new internal pairs, unusual ports (445/3389), RST bursts
- exfiltration   -> bytes_sent_mean/p95, bidirectional_byte_ratio spikes
- initial access -> inbound established session on an unusual port

All randomness flows from one seeded ``numpy.random.Generator``; identical
seeds produce byte-identical captures (reproducibility, Section 25).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

_NS = 1_000_000_000
WINDOW_NS = 30 * _NS

#: Column layout of the packet table. int64 unless noted.
PACKET_COLUMNS = (
    "t_ns", "available_ns", "ingested_ns",
    "src", "dst",                      # host indices (int32)
    "sport", "dport",                  # int32, -1 when port-less
    "proto",                           # int8: 0 tcp, 1 udp, 2 other
    "flags",                           # uint8 bitmask syn..urg
    "wire_len", "payload_len",         # int32
    "ttl",                             # int16, -1 unknown
    "tcp_window",                      # int32, -1 unknown
    "tcp_seq",                         # int64, -1 unknown
    "fragmented",                      # uint8
)

FLAG_BITS = {"syn": 1, "ack": 2, "fin": 4, "rst": 8, "psh": 16, "urg": 32}

PROTO_TCP, PROTO_UDP, PROTO_OTHER = 0, 1, 2

PROTO_MAP = {"tcp": PROTO_TCP, "udp": PROTO_UDP}

COMMON_PORTS = {
    "http": 80, "https": 443, "dns": 53, "smb": 445, "rdp": 3389,
    "ssh": 22, "sql": 1433, "mail": 25, "proxy": 8080, "backup": 873,
}


def flags(**kwargs) -> int:
    mask = 0
    for name, bit in FLAG_BITS.items():
        if kwargs.get(name):
            mask |= bit
    return mask


@dataclass(frozen=True)
class Host:
    name: str
    role: str
    address: str
    ttl: int = 64
    tcp_window: int = 65535


@dataclass(frozen=True)
class GroundTruth:
    """D.6 first-event record for one (entity, task)."""

    entity: str
    task_index: int
    event_time_ns: int
    label_tier: str = "confirmed"      # confirmed | weak_proxy | unresolved
    status: str = "observed"           # observed | not_observed (censored)


@dataclass
class BehaviorPlan:
    """Scripted traffic for one capture window of time."""

    start_ns: int
    end_ns: int
    seed: int
    behaviors: list[Callable[["CaptureBuilder"], None]] = field(default_factory=list)


class CaptureBuilder:
    """Accumulates packets for one synthetic capture.

    ``emit`` takes host indices; sequence numbers and TCP windows stay
    consistent within one directional flow (src, dst, sport, dport).
    """

    def __init__(self, hosts: list[Host], rng: np.random.Generator) -> None:
        self.hosts = hosts
        self.host_index = {h.name: i for i, h in enumerate(hosts)}
        self.rng = rng
        self.rows: list[tuple] = []
        self._seq: dict[tuple, int] = {}
        self.sensor_gaps: list[tuple[int, int, int]] = []  # (host, from, to)

    def idx(self, name: str) -> int:
        return self.host_index[name]

    def in_gap(self, host: int, at_ns: int) -> bool:
        return any(h == host and f <= at_ns <= t for h, f, t in self.sensor_gaps)

    def emit(
        self,
        at_ns: int,
        src: int,
        dst: int,
        *,
        proto: int = PROTO_TCP,
        sport: int = -1,
        dport: int = -1,
        flag_mask: int = 0,
        wire_len: int = 60,
        payload_len: int = 0,
        ttl: int | None = None,
        tcp_window: int | None = None,
        seq: int | None = None,
        fragmented: bool = False,
        ingest_delay_ns: int = 0,
    ) -> None:
        """Emit one packet row with Section-7 clocks.

        Packet telemetry is observable at reception plus a small sensor
        latency; ``ingest_delay_ns`` models extra local receipt lag (late
        arrivals exercise TM02 exclusion). Sensor gaps swallow the packet:
        a failed sensor is missingness, not a measurement (FE02).
        """
        if self.in_gap(src, at_ns) or self.in_gap(dst, at_ns):
            return
        key = (src, dst, sport, dport)
        if seq is None and proto == PROTO_TCP:
            seq = self._seq.get(key, self.rng.integers(1, 2**31))
            self._seq[key] = (seq + max(payload_len, 1) + 1) % (2**32)
        src_host, dst_host = self.hosts[src], self.hosts[dst]
        # Host-stable header defaults (observed values, not invented): TTL
        # and the advertised TCP window come from the emitting host profile.
        if ttl is None:
            ttl = src_host.ttl
        if tcp_window is None:
            tcp_window = src_host.tcp_window if proto == PROTO_TCP else -1
        sensor_latency = int(self.rng.integers(20_000_000, 90_000_000))
        available = at_ns + sensor_latency
        row = (
            at_ns,
            available,
            available + ingest_delay_ns,
            src,
            dst,
            sport,
            dport,
            proto,
            flag_mask,
            wire_len,
            payload_len,
            -1 if ttl is None else ttl,
            -1 if tcp_window is None else tcp_window,
            -1 if seq is None else seq,
            1 if fragmented else 0,
        )
        self.rows.append(row)

    # -- benign behavior primitives ----------------------------------------
    def service_call(
        self,
        at_ns: int,
        src: str,
        dst: str,
        *,
        dport: int,
        request_bytes: int = 400,
        response_bytes: int = 1200,
        established: bool = True,
    ) -> None:
        """One request/response exchange with a full handshake."""
        s, d = self.idx(src), self.idx(dst)
        sport = int(self.rng.integers(32768, 60999))
        if established:
            self.emit(at_ns, s, d, dport=dport, sport=sport,
                      flag_mask=flags(syn=True), wire_len=60)
            self.emit(at_ns + 4_000_000, d, s, dport=sport, sport=dport,
                      flag_mask=flags(syn=True, ack=True), wire_len=60)
            self.emit(at_ns + 8_000_000, s, d, dport=dport, sport=sport,
                      flag_mask=flags(ack=True), wire_len=52)
        self.emit(at_ns + 12_000_000, s, d, dport=dport, sport=sport,
                  flag_mask=flags(ack=True, psh=True), wire_len=52 + request_bytes,
                  payload_len=request_bytes)
        self.emit(at_ns + 25_000_000, d, s, dport=sport, sport=dport,
                  flag_mask=flags(ack=True, psh=True), wire_len=52 + response_bytes,
                  payload_len=response_bytes)

    def periodic_service(
        self,
        src: str,
        dst: str,
        *,
        dport: int,
        period_ns: int,
        jitter_ns: int = 2 * _NS,
        request_bytes: int = 400,
        response_bytes: int = 1200,
    ) -> None:
        """A service polled on a period (DC health, monitoring, cron)."""
        t = 0
        while t <= self.end:
            at = t + int(self.rng.integers(0, jitter_ns))
            self.service_call(at, src, dst, dport=dport,
                              request_bytes=request_bytes,
                              response_bytes=response_bytes)
            t += period_ns

    def browse_burst(
        self, at_ns: int, src: str, proxy: str, *, n_pages: int = 6
    ) -> None:
        """Web browsing via proxy: variable sizes/ports, short-lived flows."""
        s, p = self.idx(src), self.idx(proxy)
        for i in range(n_pages):
            at = at_ns + i * int(self.rng.integers(150_000_000, 900_000_000))
            req = int(self.rng.integers(300, 900))
            resp = int(self.rng.integers(2_000, 45_000))
            self.service_call(at, src, proxy, dport=COMMON_PORTS["proxy"],
                              request_bytes=req, response_bytes=resp)

    def backup_job(self, at_ns: int, src: str, dst: str, *, gib_bytes: int) -> None:
        """Bulk scheduled transfer (large sustained uploads, few packets)."""
        s, d = self.idx(src), self.idx(dst)
        sport = int(self.rng.integers(32768, 60999))
        self.emit(at_ns, s, d, dport=COMMON_PORTS["backup"], sport=sport,
                  flag_mask=flags(syn=True))
        self.emit(at_ns + 5_000_000, d, s, sport=COMMON_PORTS["backup"], dport=sport,
                  flag_mask=flags(syn=True, ack=True))
        remaining = gib_bytes
        t = at_ns + 20_000_000
        while remaining > 0:
            chunk = min(1400, remaining)
            self.emit(t, s, d, dport=COMMON_PORTS["backup"], sport=sport,
                      flag_mask=flags(ack=True, psh=True), wire_len=52 + chunk,
                      payload_len=chunk)
            remaining -= chunk
            t += int(self.rng.integers(4_000_000, 15_000_000))
            if self.rng.random() < 0.01:  # occasional retransmission
                self.emit(t, s, d, dport=COMMON_PORTS["backup"], sport=sport,
                          flag_mask=flags(ack=True, psh=True), wire_len=52 + chunk,
                          payload_len=chunk, seq=self._last_seq(s, d, sport,
                                                                COMMON_PORTS["backup"]))
                t += 8_000_000

    def _last_seq(self, src: int, dst: int, sport: int, dport: int) -> int:
        return self._seq.get((src, dst, sport, dport), 1000) - 1400

    # -- attack stage primitives -------------------------------------------
    def port_scan(
        self,
        at_ns: int,
        src: str,
        dst: str,
        *,
        n_ports: int = 120,
        rate_per_s: float = 20.0,
        sequential: bool = True,
        start_port: int = 440,
    ) -> None:
        """SYN sweep: sequential or shuffled ports; most attempts unanswered
        (matured timeouts), some RSTs, occasional SYN/ACK."""
        s, d = self.idx(src), self.idx(dst)
        step_ns = int(_NS / rate_per_s)
        port_list = (
            np.arange(start_port, start_port + n_ports)
            if sequential
            else self.rng.choice(np.arange(1, 65535), size=n_ports, replace=False)
        )
        for i, port in enumerate(port_list):
            at = at_ns + i * step_ns
            sport = int(self.rng.integers(32768, 60999))
            self.emit(at, s, d, dport=int(port), sport=sport,
                      flag_mask=flags(syn=True), wire_len=60)
            roll = self.rng.random()
            if roll < 0.1:  # some services answer
                self.emit(at + 3_000_000, d, s, sport=int(port), dport=sport,
                          flag_mask=flags(syn=True, ack=True))
            elif roll < 0.25:  # some reset
                self.emit(at + 2_000_000, d, s, sport=int(port), dport=sport,
                          flag_mask=flags(rst=True, ack=True), wire_len=60)

    def beacon(
        self,
        at_ns: int,
        src: str,
        dst: str,
        *,
        duration_ns: int,
        interval_ns: int = 30 * _NS,
        jitter_ns: int = 200_000_000,
        payload: int = 128,
    ) -> None:
        """C2 beacon: fixed-size payload, regular interval, small jitter
        (low iat_variance), one established long-lived flow."""
        s, d = self.idx(src), self.idx(dst)
        sport = int(self.rng.integers(32768, 60999))
        dport = int(self.rng.choice([443, 8443, 53]))
        self.emit(at_ns, s, d, dport=dport, sport=sport, flag_mask=flags(syn=True))
        self.emit(at_ns + 30_000_000, d, s, sport=dport, dport=sport,
                  flag_mask=flags(syn=True, ack=True))
        t = at_ns + 100_000_000
        while t <= at_ns + duration_ns:
            at = t + int(self.rng.integers(0, jitter_ns))
            self.emit(at, s, d, dport=dport, sport=sport,
                      flag_mask=flags(ack=True, psh=True),
                      wire_len=52 + payload, payload_len=payload)
            self.emit(at + int(self.rng.integers(20_000_000, 60_000_000)), d, s,
                      sport=dport, dport=sport, flag_mask=flags(ack=True),
                      wire_len=52)
            t += interval_ns

    def exploit_access(self, at_ns: int, ext: str, dst: str, *, dport: int) -> None:
        """Initial access: inbound established session on an unusual port."""
        e, d = self.idx(ext), self.idx(dst)
        sport = int(self.rng.integers(32768, 60999))
        self.emit(at_ns, e, d, dport=dport, sport=sport, flag_mask=flags(syn=True))
        self.emit(at_ns + 12_000_000, d, e, sport=dport, dport=sport,
                  flag_mask=flags(syn=True, ack=True))
        for i in range(8):
            at = at_ns + 30_000_000 + i * 90_000_000
            self.emit(at, e, d, dport=dport, sport=sport,
                      flag_mask=flags(ack=True, psh=True),
                      wire_len=52 + 300, payload_len=300)
            self.emit(at + 40_000_000, d, e, sport=dport, dport=sport,
                      flag_mask=flags(ack=True, psh=True),
                      wire_len=52 + 900, payload_len=900)

    def lateral_session(
        self, at_ns: int, src: str, dst: str, *, dport: int = COMMON_PORTS["smb"]
    ) -> None:
        """Lateral movement: internal host reaches new peer on admin port
        with bursty multi-packet exchange and some failed attempts."""
        s, d = self.idx(src), self.idx(dst)
        for attempt in range(3):
            sport = int(self.rng.integers(32768, 60999))
            at = at_ns + attempt * 400_000_000
            if attempt == 1:  # one denied attempt first
                self.emit(at, s, d, dport=dport, sport=sport,
                          flag_mask=flags(syn=True))
                self.emit(at + 6_000_000, d, s, sport=dport, dport=sport,
                          flag_mask=flags(rst=True, ack=True))
                continue
            self.emit(at, s, d, dport=dport, sport=sport, flag_mask=flags(syn=True))
            self.emit(at + 5_000_000, d, s, sport=dport, dport=sport,
                      flag_mask=flags(syn=True, ack=True))
            for k in range(10):
                t = at + 15_000_000 + k * 30_000_000
                up = int(self.rng.integers(200, 1600))
                down = int(self.rng.integers(300, 2400))
                self.emit(t, s, d, dport=dport, sport=sport,
                          flag_mask=flags(ack=True, psh=True),
                          wire_len=52 + up, payload_len=up)
                self.emit(t + 15_000_000, d, s, sport=dport, dport=sport,
                          flag_mask=flags(ack=True, psh=True),
                          wire_len=52 + down, payload_len=down)

    def exfil_transfer(
        self, at_ns: int, src: str, dst: str, *, total_bytes: int
    ) -> None:
        """Bulk exfiltration: sustained large outbound payload stream."""
        s, d = self.idx(src), self.idx(dst)
        sport = int(self.rng.integers(32768, 60999))
        dport = 443
        self.emit(at_ns, s, d, dport=dport, sport=sport, flag_mask=flags(syn=True))
        self.emit(at_ns + 20_000_000, d, s, sport=dport, dport=sport,
                  flag_mask=flags(syn=True, ack=True))
        remaining = total_bytes
        t = at_ns + 60_000_000
        while remaining > 0:
            chunk = min(1400, remaining)
            self.emit(t, s, d, dport=dport, sport=sport,
                      flag_mask=flags(ack=True, psh=True),
                      wire_len=52 + chunk, payload_len=chunk)
            remaining -= chunk
            t += int(self.rng.integers(3_000_000, 9_000_000))
        self.emit(t + 10_000_000, s, d, dport=dport, sport=sport,
                  flag_mask=flags(fin=True, ack=True))


@dataclass
class SyntheticCapture:
    """One generated capture: packet table, hosts, labels, provenance."""

    capture_id: str
    hosts: tuple[Host, ...]
    packets: np.ndarray            # structured array, PACKET_COLUMNS
    ground_truth: tuple[GroundTruth, ...]
    start_ns: int
    end_ns: int
    sensor_gaps: tuple[tuple[str, int, int], ...]
    campaign: str
    family: str
    seed: int
    synthetic: bool = True

    @property
    def host_names(self) -> tuple[str, ...]:
        return tuple(h.name for h in self.hosts)

    def host_address(self, name: str) -> str:
        for h in self.hosts:
            if h.name == name:
                return h.address
        raise KeyError(name)

    def table(self) -> dict:
        """Manifest summary for the session/API layer."""
        return {
            "capture_id": self.capture_id,
            "campaign": self.campaign,
            "family": self.family,
            "seed": self.seed,
            "synthetic": self.synthetic,
            "host_count": len(self.hosts),
            "packet_count": int(len(self.packets)),
            "start_ns": str(self.start_ns),
            "end_ns": str(self.end_ns),
            "sensor_gaps": [
                {"host": h, "from_ns": str(f), "to_ns": str(t)}
                for h, f, t in self.sensor_gaps
            ],
            "ground_truth": [
                {
                    "entity": g.entity,
                    "task_index": g.task_index,
                    "event_time_ns": str(g.event_time_ns),
                    "label_tier": g.label_tier,
                    "status": g.status,
                }
                for g in self.ground_truth
            ],
        }


def finalize_table(rows: list[tuple]) -> np.ndarray:
    dtype = np.dtype(
        [
            ("t_ns", "<i8"), ("available_ns", "<i8"), ("ingested_ns", "<i8"),
            ("src", "<i4"), ("dst", "<i4"),
            ("sport", "<i4"), ("dport", "<i4"),
            ("proto", "i1"), ("flags", "u1"),
            ("wire_len", "<i4"), ("payload_len", "<i4"),
            ("ttl", "<i2"), ("tcp_window", "<i4"),
            ("tcp_seq", "<i8"), ("fragmented", "u1"),
        ]
    )
    table = np.zeros(len(rows), dtype=dtype)
    for i, row in enumerate(rows):
        table[i] = row
    order = np.lexsort((table["ingested_ns"], table["t_ns"]))
    return table[order]


def generate_capture(
    *,
    capture_id: str,
    campaign: str,
    family: str,
    seed: int,
    duration_ns: int,
    script: Callable[[CaptureBuilder], list[GroundTruth]],
    hosts: list[Host],
    sensor_gaps: list[tuple[str, int, int]] | None = None,
    late_arrival_rate: float = 0.01,
) -> SyntheticCapture:
    """Run one capture script deterministically from ``seed``."""
    rng = np.random.default_rng(seed)
    builder = CaptureBuilder(hosts, rng)
    builder.start = 0
    builder.end = duration_ns
    builder.sensor_gaps = [
        (builder.idx(name), f, t) for name, f, t in (sensor_gaps or [])
    ]
    ground_truth = script(builder)
    table = finalize_table(builder.rows)

    # Late arrivals: a small fraction gets extra ingest delay of 3-8 minutes,
    # exercising TM02 (event before d, receipt after d -> excluded).
    if late_arrival_rate > 0 and len(table):
        draw = rng.random(len(table))
        late = draw < late_arrival_rate
        extra = rng.integers(180 * _NS, 480 * _NS, size=len(table))
        table["ingested_ns"] = np.where(
            late, table["ingested_ns"] + extra, table["ingested_ns"]
        )

    return SyntheticCapture(
        capture_id=capture_id,
        hosts=tuple(hosts),
        packets=table,
        ground_truth=tuple(ground_truth),
        start_ns=int(table["t_ns"].min()) if len(table) else 0,
        end_ns=int(duration_ns),
        sensor_gaps=tuple(
            (hosts[h].name, f, t) for h, f, t in builder.sensor_gaps
        ),
        campaign=campaign,
        family=family,
        seed=seed,
    )
