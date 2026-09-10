"""Flow segmentation and TCP attempt semantics (Build Spec F.2, F.3).

A flow is a directional five-tuple segment keyed by (tenant, sensor
observation domain, protocol, source identity, source port, destination
identity, destination port), segmented on the 30-second idle timeout or
120-second active timeout (F.2). Only observed per-window deltas are exposed:
lifetime totals are never copied into every window (FE04).

TCP failure classification (F.3): a SYN without ACK begins an attempt; a
matching SYN/ACK or established data supports success; an observed RST or a
matured no-response timeout supports failure only under bidirectional
coverage. Pending attempts stay pending (FE03); duplicate SYN retransmissions
do not multiply attempts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.events import PacketObservables, SecurityEvent

#: F.2 defaults (Section 9): 30 s idle timeout, 120 s active segment timeout.
FLOW_DEFAULTS = {
    "idle_timeout_ns": 30 * 1_000_000_000,
    "active_timeout_ns": 120 * 1_000_000_000,
}

#: F.3 synthetic-fixture profile: 3 s no-response maturity timeout.
TCP_ATTEMPT_TIMEOUT_NS = 3 * 1_000_000_000

_NS = 1_000_000_000


@dataclass
class SegmentAccumulator:
    """F.2 segment accumulator: observed packets, byte totals, first/last
    observed time, IAT statistics, flag counts and source locators."""

    key: tuple
    start_ns: int
    last_ns: int
    packets: list[tuple[int, PacketObservables]] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)

    @property
    def bytes_total(self) -> int:
        return sum(p.wire_length for _, p in self.packets)

    @property
    def idle_ns(self) -> int:
        return self.last_ns - self.start_ns

    def add(self, at_ns: int, obs: PacketObservables, event_id: str) -> None:
        self.packets.append((at_ns, obs))
        self.event_ids.append(event_id)
        if at_ns < self.start_ns:
            self.start_ns = at_ns
        if at_ns > self.last_ns:
            self.last_ns = at_ns


@dataclass
class FlowSegment:
    """One closed (or window-sampled) directional segment."""

    key: tuple  # (protocol, src_key, sport, dst_key, dport)
    start_ns: int
    end_ns: int
    packets: tuple[tuple[int, PacketObservables], ...]
    event_ids: tuple[str, ...]

    @property
    def observed_packet_count(self) -> int:
        return len(self.packets)

    def packets_in_window(self, start_ns: int, end_ns: int):
        """Packets with ``start_ns < t <= end_ns`` (F.5 (start, end] grid)."""
        return [p for p in self.packets if start_ns < p[0] <= end_ns]


def segment_key(obs: PacketObservables, resolve) -> tuple:
    """Directional segment key (F.2). ``resolve`` maps an address to the
    frozen identity key (identity G.1), not a numeric feature."""
    return (
        obs.protocol,
        resolve(obs.src_address),
        obs.src_port,
        resolve(obs.dst_address),
        obs.dst_port,
    )


def segment_packets(
    packets: list[tuple[int, PacketObservables, str]],
    resolve,
    *,
    idle_timeout_ns: int = FLOW_DEFAULTS["idle_timeout_ns"],
    active_timeout_ns: int = FLOW_DEFAULTS["active_timeout_ns"],
) -> list[FlowSegment]:
    """Segment an ordered packet stream into directional flow segments.

    ``packets`` are ``(event_time_ns, observables, event_id)`` sorted by event
    time. A new segment opens on key change, idle timeout or active timeout;
    segment closure is an observation event, not a retroactive change (F.2).
    """
    segments: list[FlowSegment] = []
    open_by_key: dict[tuple, SegmentAccumulator] = {}

    for at_ns, obs, event_id in packets:
        key = segment_key(obs, resolve)
        acc = open_by_key.get(key)
        if acc is not None and (
            at_ns - acc.last_ns > idle_timeout_ns
            or at_ns - acc.start_ns > active_timeout_ns
        ):
            segments.append(_close(acc))
            acc = None
            del open_by_key[key]
        if acc is None:
            acc = SegmentAccumulator(key=key, start_ns=at_ns, last_ns=at_ns)
            open_by_key[key] = acc
        acc.add(at_ns, obs, event_id)

    for acc in open_by_key.values():
        segments.append(_close(acc))
    segments.sort(key=lambda s: (s.start_ns, s.key))
    return segments


def _close(acc: SegmentAccumulator) -> FlowSegment:
    ordered = sorted(acc.packets, key=lambda p: p[0])
    return FlowSegment(
        key=acc.key,
        start_ns=ordered[0][0],
        end_ns=ordered[-1][0],
        packets=tuple(ordered),
        event_ids=tuple(acc.event_ids),
    )


@dataclass
class AttemptClassification:
    """F.3 matured attempt classification, assigned at its availability time."""

    src_key: str
    dst_key: str
    dst_port: int | None
    begin_ns: int
    classified_at_ns: int
    outcome: str  # "success" | "failed" | "timeout_failed"


class TcpAttemptTracker:
    """F.3 connection-attempt semantics over a packet stream.

    - SYN without ACK begins an attempt (keyed by the directional segment
      tuple; duplicate SYN retransmissions keep the same attempt — FE03).
    - Matching SYN/ACK or established (ACK with payload) evidence supports
      success at the response time.
    - Observed RST supports failure at the RST time.
    - No response supports failure only after the maturity timeout AND
      bidirectional coverage for the pair; otherwise pending stays pending.
    """

    def __init__(
        self,
        *,
        timeout_ns: int = TCP_ATTEMPT_TIMEOUT_NS,
        bidirectional_coverage: set[tuple[str, str]] | None = None,
    ) -> None:
        self.timeout_ns = timeout_ns
        self.coverage = bidirectional_coverage or set()
        self._open: dict[tuple, dict] = {}
        self.classifications: list[AttemptClassification] = []

    def observe(self, at_ns: int, obs: PacketObservables, src_key: str, dst_key: str) -> None:
        if obs.protocol != "tcp":
            return
        flags = obs.flag_bits
        attempt_key = (src_key, dst_key, obs.src_port, obs.dst_port)
        attempt = self._open.get(attempt_key)

        if flags["syn"] and not flags["ack"]:
            if attempt is None:
                self._open[attempt_key] = {
                    "src": src_key,
                    "dst": dst_key,
                    "dport": obs.dst_port,
                    "begin_ns": at_ns,
                    "matures_ns": at_ns + self.timeout_ns,
                    "seq": obs.tcp_sequence,
                }
            # duplicate SYN retransmission: same attempt (FE03)
            return

        if attempt is None:
            return

        if flags["syn"] and flags["ack"]:
            self._finish(attempt_key, attempt, at_ns, "success")
            return
        if flags["rst"]:
            # RST from the responder direction closes the attempt as failed;
            # an RST from the initiator (client abort) also classifies it.
            self._finish(attempt_key, attempt, at_ns, "failed")
            return
        if flags["ack"] and (obs.transport_payload_length or 0) > 0:
            self._finish(attempt_key, attempt, at_ns, "success")
            return

    def _finish(self, key, attempt: dict, at_ns: int, outcome: str) -> None:
        del self._open[key]
        self.classifications.append(
            AttemptClassification(
                src_key=attempt["src"],
                dst_key=attempt["dst"],
                dst_port=attempt["dport"],
                begin_ns=attempt["begin_ns"],
                classified_at_ns=at_ns,
                outcome=outcome,
            )
        )

    def mature(self, upto_ns: int) -> None:
        """Classify timed-out attempts whose maturity time has arrived.

        Timeout-based failure requires bidirectional observation coverage for
        the pair (F.3); without it the attempt remains pending forever.
        """
        for key in list(self._open):
            attempt = self._open[key]
            if attempt["matures_ns"] > upto_ns:
                continue
            pair = (attempt["dst"], attempt["src"])  # reverse direction seen?
            if pair not in self.coverage and (attempt["src"], attempt["dst"]) not in self.coverage:
                continue
            del self._open[key]
            self.classifications.append(
                AttemptClassification(
                    src_key=attempt["src"],
                    dst_key=attempt["dst"],
                    dst_port=attempt["dport"],
                    begin_ns=attempt["begin_ns"],
                    classified_at_ns=attempt["matures_ns"],
                    outcome="timeout_failed",
                )
            )


def retransmission_overlaps(
    packets: list[tuple[int, PacketObservables]],
) -> tuple[int, int]:
    """Bounded TCP retransmission heuristic (F.3): counts retransmitted
    payload packets and eligible payload packets from sequence-number overlap.

    Returns ``(retransmitted_payload_packets, eligible_payload_packets)``.
    Sequence wrap is tracked; duplicate sequence+length pairs count as
    retransmissions. Only packets with both sequence and payload length are
    eligible (sufficient sequence visibility).
    """
    eligible = [
        (at, obs)
        for at, obs in packets
        if obs.protocol == "tcp"
        and obs.tcp_sequence is not None
        and (obs.transport_payload_length or 0) > 0
    ]
    seen_intervals: list[tuple[int, int]] = []
    retransmitted = 0
    wrap = 1 << 32
    for _, obs in eligible:
        start = obs.tcp_sequence % wrap
        end = start + obs.transport_payload_length
        overlap = any(
            not (end <= s or start >= e) for s, e in seen_intervals
        )
        if overlap:
            retransmitted += 1
        seen_intervals.append((start, end))
    return retransmitted, len(eligible)


def eligible_packets(
    events: list[SecurityEvent], cutoff_ns: int
) -> list[SecurityEvent]:
    """Section 7 cutoff filter: all three clocks at or before ``d``."""
    return [e for e in events if e.eligible_at(cutoff_ns)]
