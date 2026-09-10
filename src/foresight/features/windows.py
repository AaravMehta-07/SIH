"""GraphWindow construction from eligible packet telemetry (F.5-F.7).

``build_clip_windows`` produces the raw (unscaled) D.5 windows for one
decision clip: the 20 completed 30-second windows ending at cutoff ``d``,
using only packets whose event/availability/ingestion clocks are all at or
before ``d`` (Section 7; TM02/TM03).

Every feature follows the F.6/F.7 definition exactly, including missingness
rules: healthy idle counts are valid zeros; empty-denominator statistics are
invalid (masked), never reassuring zeros (FE02). Sources without a field
group (flow-CSV) mask the dependent features instead of inventing values
(Section 9, D.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..ingest.synthetic import FLAG_BITS, PROTO_TCP, PROTO_UDP
from .registry import PAYLOAD_BINS

WINDOW_SECONDS = 30
_NS = 1_000_000_000

_SYN = FLAG_BITS["syn"]
_ACK = FLAG_BITS["ack"]
_FIN = FLAG_BITS["fin"]
_RST = FLAG_BITS["rst"]
_PSH = FLAG_BITS["psh"]
_URG = FLAG_BITS["urg"]

_N_NODE = 44
_N_EDGE = 11
_N_GLOBAL = 24

#: Field groups a packet-telemetry source provides (F.1 allowlist). The
#: flow-CSV profile lacks most of them; its builder call passes the reduced
#: set so dependent features are masked (never fabricated).
FULL_PACKET_CAPABILITIES = frozenset(
    {
        "packet_timing",
        "packet_lengths",
        "ip_addresses",
        "transport_ports",
        "tcp_flags",
        "tcp_sequence",
        "tcp_window",
        "ip_ttl",
        "ip_fragmentation",
        "transport_payload_length",
    }
)

#: Feature positions masked when a capability group is absent.
_CAPABILITY_MASKS: dict[str, tuple[int, ...]] = {
    "tcp_flags": (0, 1, 2, 3, 4, 5, 6, 7, 8),
    "packet_timing": (25, 26, 27, 28, 29, 30, 31),
    "ip_ttl": (32, 33),
    "tcp_window": (34, 35),
    "tcp_sequence": (36,),
    "ip_fragmentation": (37,),
    "transport_payload_length": (38, 39, 40, 41, 42),
    "transport_ports": (10, 11, 12, 43),
}


def window_bounds(
    cutoff_ns: int, num_windows: int, window_ns: int = WINDOW_SECONDS * _NS
) -> list[tuple[int, int]]:
    """The ``num_windows`` completed ``(start, end]`` grid windows ending at
    ``cutoff_ns``, oldest first. A packet exactly on a boundary belongs to
    the preceding window (F.5, TM05)."""
    end = int(cutoff_ns)
    bounds = []
    for _ in range(num_windows):
        start = end - window_ns
        bounds.append((start, end))
        end = start
    return list(reversed(bounds))


@dataclass
class EvidenceIndex:
    """Feature-to-source reference table (D.5). Maps (slot, group) and
    (src_slot, dst_slot) to contributing packet row indices so every
    displayed aggregate traces to legal prefix packets (EX02)."""

    node_groups: dict[tuple[int, str], list[int]] = field(default_factory=dict)
    edge_groups: dict[tuple[int, int], list[int]] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "node_groups": {
                f"{slot}:{group}": rows
                for (slot, group), rows in self.node_groups.items()
            },
            "edge_groups": {
                f"{src}-{dst}": rows for (src, dst), rows in self.edge_groups.items()
            },
        }


@dataclass
class RawGraphWindow:
    """D.5 GraphWindow: unscaled values, masks, evidence, provenance."""

    window_start_ns: int
    window_end_ns: int
    decision_cutoff_ns: int
    ordered_entity_ids: tuple[str, ...]
    node_values: np.ndarray          # float32 [N, 44]
    node_validity: np.ndarray        # bool [N, 44]
    edge_index: np.ndarray           # int64 [2, E] slots
    edge_values: np.ndarray          # float32 [E, 11]
    edge_validity: np.ndarray        # bool [E, 11]
    global_values: np.ndarray        # float32 [24]
    global_validity: np.ndarray      # bool [24]
    node_present: np.ndarray         # bool [N]
    node_observation_valid: np.ndarray  # bool [N]
    evidence: EvidenceIndex
    feature_registry_hash: str = ""
    raw_prefix_hash: str = ""
    window_index: int = 0


def _quantile(sorted_values: np.ndarray, q: float) -> float:
    """F.6 linear interpolation: r=(n-1)*p, interpolate floor/ceil."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_values[0])
    r = (n - 1) * q
    lo = int(np.floor(r))
    hi = int(np.ceil(r))
    if lo == hi:
        return float(sorted_values[lo])
    frac = r - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


def _popvar(values: np.ndarray) -> float:
    """Population variance (divisor n, F.6); a sole sample is valid zero."""
    if len(values) < 2:
        return 0.0
    return float(np.var(values))


def _entropy_normalized(counts: np.ndarray) -> float:
    """Shannon entropy of packet frequencies over K distinct ports divided by
    log(K); 0 when K == 1 (F.6 row 12)."""
    total = counts.sum()
    if total <= 0 or len(counts) == 0:
        return 0.0
    if len(counts) == 1:
        return 0.0
    p = counts / total
    h = float(-(p * np.log(p)).sum())
    return h / float(np.log(len(counts)))


class _AttemptTracker:
    """F.3 cross-window TCP attempt classification (FE03).

    A SYN without ACK begins an attempt keyed by the directional tuple;
    duplicate SYN retransmissions keep the same attempt. SYN/ACK, established
    data or RST classify at the response time; silence classifies as failure
    only after the 3-second maturity timeout AND bidirectional pair coverage.
    """

    def __init__(self, timeout_ns: int, coverage: set[tuple[int, int]]) -> None:
        self.timeout_ns = timeout_ns
        self.coverage = coverage
        self.open: dict[tuple, dict] = {}

    def feed(self, rows: np.ndarray, host_of: dict[int, int]) -> dict[tuple[int, int], list]:
        matured: dict[tuple[int, int], list] = {}
        for row in rows:
            if row["proto"] != PROTO_TCP:
                continue
            f = int(row["flags"])
            src = host_of[int(row["src"])]
            dst = host_of[int(row["dst"])]
            sport = int(row["sport"])
            dport = int(row["dport"])
            fwd_key = (src, dst, sport, dport)
            # A response row (responder -> initiator) reverses the tuple.
            rev_key = (dst, src, dport, sport)
            if f & _SYN and not f & _ACK:
                if fwd_key not in self.open:
                    self.open[fwd_key] = {
                        "src": src,
                        "dst": dst,
                        "matures_ns": int(row["t_ns"]) + self.timeout_ns,
                    }
                continue  # duplicate SYN retransmission keeps one attempt
            if f & _ACK and int(row["payload_len"]) == 0 and not (f & _RST):
                # bare ACKs close nothing on their own
                if fwd_key not in self.open and rev_key not in self.open:
                    continue
            attempt_key = (
                fwd_key if fwd_key in self.open
                else rev_key if rev_key in self.open
                else None
            )
            if attempt_key is None:
                continue
            attempt = self.open[attempt_key]
            if f & _SYN and f & _ACK:
                self._close(attempt_key, attempt, matured, "success")
            elif f & _RST:
                self._close(attempt_key, attempt, matured, "failed")
            elif f & _ACK and int(row["payload_len"]) > 0:
                self._close(attempt_key, attempt, matured, "success")
        return matured

    def _close(self, key, attempt, matured, outcome) -> None:
        del self.open[key]
        matured.setdefault((attempt["src"], attempt["dst"]), []).append(outcome)

    def expire(self, upto_ns: int) -> dict[tuple[int, int], list]:
        matured: dict[tuple[int, int], list] = {}
        for key in list(self.open):
            attempt = self.open[key]
            if attempt["matures_ns"] > upto_ns:
                continue
            if (attempt["src"], attempt["dst"]) not in self.coverage and (
                attempt["dst"], attempt["src"]
            ) not in self.coverage:
                continue
            del self.open[key]
            matured.setdefault((attempt["src"], attempt["dst"]), []).append("failed")
        return matured


def build_clip_windows(
    packets: np.ndarray,
    *,
    entity_ids: tuple[str, ...],
    entity_of_host: dict[int, int],
    internal_hosts: set[int],
    cutoff_ns: int,
    history_windows: int = 20,
    sensor_gap_hosts: dict[int, list[tuple[int, int]]] | None = None,
    capabilities: frozenset[str] = FULL_PACKET_CAPABILITIES,
    registry_hash: str = "",
    prefix_hash: str = "",
) -> list[RawGraphWindow]:
    """Build the raw 20-window clip ending at ``cutoff_ns``.

    ``entity_of_host`` maps table host indices to entity slots; hosts in
    ``internal_hosts`` are graph nodes (external addresses aggregate into
    host features only, F.7).
    """
    bounds = window_bounds(cutoff_ns, history_windows)

    # Section 7 eligibility, applied once per cutoff (TM02/TM03).
    eligible = (
        (packets["t_ns"] <= cutoff_ns)
        & (packets["available_ns"] <= cutoff_ns)
        & (packets["ingested_ns"] <= cutoff_ns)
    )
    table = packets[eligible]

    # Bidirectional pair coverage for timeout-based failure classification
    # (F.3): entity pairs with observed communication in both directions.
    if len(table):
        fwd = set(
            zip(
                (entity_of_host[int(h)] for h in table["src"]),
                (entity_of_host[int(h)] for h in table["dst"]),
            )
        )
        coverage = {(a, b) for (a, b) in fwd if (b, a) in fwd}
    else:
        coverage = set()

    gaps = sensor_gap_hosts or {}
    tracker = _AttemptTracker(timeout_ns=3 * _NS, coverage=coverage)
    seen_keys: set[int] = set()             # clip-relative segment keys
    seen_pairs: set[tuple[int, int]] = set()  # past-only internal pair set

    windows: list[RawGraphWindow] = []
    for w_index, (start, end) in enumerate(bounds):
        rows = table[(table["t_ns"] > start) & (table["t_ns"] <= end)]
        windows.append(
            _build_one_window(
                rows,
                w_index=w_index,
                start=start,
                end=end,
                cutoff=cutoff_ns,
                entity_ids=entity_ids,
                entity_of_host=entity_of_host,
                internal_hosts=internal_hosts,
                tracker=tracker,
                seen_keys=seen_keys,
                seen_pairs=seen_pairs,
                sensor_gaps=gaps,
                capabilities=capabilities,
                registry_hash=registry_hash,
                prefix_hash=prefix_hash,
            )
        )
    return windows


def _build_one_window(
    rows: np.ndarray,
    *,
    w_index: int,
    start: int,
    end: int,
    cutoff: int,
    entity_ids: tuple[str, ...],
    entity_of_host: dict[int, int],
    internal_hosts: set[int],
    tracker: _AttemptTracker,
    seen_keys: set,
    seen_pairs: set,
    sensor_gaps: dict[int, list[tuple[int, int]]],
    capabilities: frozenset[str],
    registry_hash: str,
    prefix_hash: str,
) -> RawGraphWindow:
    n = len(entity_ids)
    host_of = entity_of_host
    caps = capabilities

    node_values = np.zeros((n, _N_NODE), dtype=np.float32)
    node_valid = np.zeros((n, _N_NODE), dtype=bool)

    if len(rows):
        src_slot = np.array([host_of[int(h)] for h in rows["src"]], dtype=np.int64)
        dst_slot = np.array([host_of[int(h)] for h in rows["dst"]], dtype=np.int64)
        flags = rows["flags"].astype(np.int64)
        times = rows["t_ns"]
    else:
        src_slot = np.zeros(0, dtype=np.int64)
        dst_slot = np.zeros(0, dtype=np.int64)
        flags = np.zeros(0, dtype=np.int64)
        times = np.zeros(0, dtype=np.int64)

    # Observation health: a sensor gap masks the channel (all features stay
    # invalid), while a healthy idle host keeps valid zeros (FE02).
    obs_valid = np.ones(n, dtype=bool)
    for host, intervals in sensor_gaps.items():
        slot = host_of[host]
        for f, t in intervals:
            if f <= end and t >= start:
                obs_valid[slot] = False

    # Capability masking: unobservable groups mask dependent features (D.4).
    for group, positions in _CAPABILITY_MASKS.items():
        if group not in caps:
            for pos in positions:
                node_valid[:, pos] = False

    # ---- segment keys active in this window (F.2: same key = one segment) --
    if len(rows):
        seg_keys = (
            rows["src"].astype(np.int64) * (2**48)
            + rows["dst"].astype(np.int64) * (2**32)
            + np.where(rows["sport"] >= 0, rows["sport"], 0).astype(np.int64) * (2**16)
            + np.where(rows["dport"] >= 0, rows["dport"], 0).astype(np.int64)
            + rows["proto"].astype(np.int64) * (2**62)
        )
        uniq, inv = np.unique(seg_keys, return_inverse=True)
    else:
        uniq = np.zeros(0, dtype=np.int64)
        inv = np.zeros(0, dtype=np.int64)

    flow_starts = 0
    for key in uniq.tolist():
        if key not in seen_keys:
            seen_keys.add(key)
            flow_starts += 1

    # ---- features 1-9: flags and matured connection attempts ---------------
    tcp_out = rows["proto"] == PROTO_TCP if len(rows) else np.zeros(0, dtype=bool)
    for slot in range(n):
        m = src_slot == slot
        if not m.any():
            continue
        if "tcp_flags" in caps:
            mt = m & tcp_out
            f = flags[mt]
            node_values[slot, 0] = int((f & _SYN != 0).sum())
            node_values[slot, 1] = int((f & _ACK != 0).sum())
            node_values[slot, 2] = int((f & _FIN != 0).sum())
            node_values[slot, 3] = int((f & _RST != 0).sum())
            node_values[slot, 4] = int((f & _PSH != 0).sum())
            node_values[slot, 5] = int((f & _URG != 0).sum())
            node_valid[slot, 0:6] = True
            node_values[slot, 6] = node_values[slot, 0] / (node_values[slot, 1] + 1)
            node_valid[slot, 6] = True
            tcp_count = int(mt.sum())
            if tcp_count > 0:
                node_values[slot, 7] = node_values[slot, 3] / tcp_count
                node_valid[slot, 7] = True

    # F.6: counts are valid zero for a healthy empty observation domain — a
    # present, observed idle host carries valid zeros, never masked counts
    # (FE02: healthy idle differs from a failed observation channel).
    if len(rows):
        for slot in range(n):
            if obs_valid[slot] and not (src_slot == slot).any():
                if "tcp_flags" in caps:
                    node_valid[slot, 0:7] = True
                if "ip_addresses" in caps:
                    node_valid[slot, 9] = True
                if "transport_ports" in caps:
                    node_valid[slot, 10] = True

    matured = tracker.feed(rows, host_of)
    expired = tracker.expire(end)
    for key, outcomes in expired.items():
        matured.setdefault(key, []).extend(outcomes)
    per_src: dict[int, list] = {}
    for (src, _dst), outcomes in matured.items():
        if src < n:
            per_src.setdefault(src, []).extend(outcomes)
    for src, outcomes in per_src.items():
        failures = sum(1 for o in outcomes if o == "failed")
        node_values[src, 8] = failures / len(outcomes)
        node_valid[src, 8] = "tcp_flags" in caps

    # ---- features 10-13, 44: destinations and ports ------------------------
    for slot in range(n):
        m = src_slot == slot
        if not m.any():
            continue
        node_values[slot, 9] = len(np.unique(dst_slot[m]))
        node_valid[slot, 9] = "ip_addresses" in caps
        if "transport_ports" not in caps:
            continue
        dports = rows["dport"][m]
        has_port = dports >= 0
        if not has_port.any():
            continue
        ports = dports[has_port]
        distinct = np.unique(ports)
        node_values[slot, 10] = len(distinct)
        node_valid[slot, 10] = True
        counts = np.array([(ports == p).sum() for p in distinct], dtype=float)
        node_values[slot, 11] = _entropy_normalized(counts)
        node_valid[slot, 11] = True
        if len(distinct) >= 2:
            adj = np.abs(np.diff(np.sort(distinct)))
            node_values[slot, 12] = float((adj == 1).sum()) / (len(distinct) - 1)
            node_valid[slot, 12] = True
            # 44: first-seen order, deterministic ties by observation order
            order_time = times[m][has_port]
            order_idx = np.argsort(order_time, kind="stable")
            ordered_ports, seen_p = [], set()
            for p in ports[order_idx]:
                if int(p) not in seen_p:
                    seen_p.add(int(p))
                    ordered_ports.append(int(p))
            diffs = np.abs(np.diff(np.array(ordered_ports)))
            node_values[slot, 43] = float((diffs == 1).sum()) / (len(ordered_ports) - 1)
            node_valid[slot, 43] = True

    # ---- internal directed pairs: degrees 14-16 -----------------------------
    if len(rows):
        src_internal = np.array([int(h) in internal_hosts for h in rows["src"]])
        dst_internal = np.array([int(h) in internal_hosts for h in rows["dst"]])
        edge_rows = np.where(src_internal & dst_internal)[0]
    else:
        edge_rows = np.zeros(0, dtype=np.int64)

    pair_byte: dict[tuple[int, int], int] = {}
    pair_packets: dict[tuple[int, int], int] = {}
    pair_rows: dict[tuple[int, int], list[int]] = {}
    for i in edge_rows:
        u, v = int(src_slot[i]), int(dst_slot[i])
        pair_byte[(u, v)] = pair_byte.get((u, v), 0) + int(rows["wire_len"][i])
        pair_packets[(u, v)] = pair_packets.get((u, v), 0) + 1
        pair_rows.setdefault((u, v), []).append(int(i))

    in_deg = np.zeros(n, dtype=np.int64)
    out_deg = np.zeros(n, dtype=np.int64)
    for (u, v) in pair_byte:
        out_deg[u] += 1
        in_deg[v] += 1
    node_values[:, 13] = in_deg
    node_values[:, 14] = out_deg
    node_values[:, 15] = (out_deg + 1) / (in_deg + 1)
    node_valid[:, 13:16] = True

    # ---- segment-level features 17-32 (per-window deltas, FE04) ------------
    if len(rows):
        seg_bytes = np.bincount(inv, weights=rows["wire_len"], minlength=len(uniq))
        seg_count = np.bincount(inv, minlength=len(uniq))
        seg_first = np.full(len(uniq), np.iinfo(np.int64).max, dtype=np.int64)
        seg_last = np.zeros(len(uniq), dtype=np.int64)
        np.minimum.at(seg_first, inv, times)
        np.maximum.at(seg_last, inv, times)
        first_idx = np.unique(inv, return_index=True)[1]
        seg_slot_src = src_slot[first_idx]
        seg_slot_dst = dst_slot[first_idx]

        for slot in range(n):
            out_seg = seg_slot_src == slot
            in_seg = seg_slot_dst == slot
            if out_seg.any():
                b = np.sort(seg_bytes[out_seg])
                p = np.sort(seg_count[out_seg].astype(float))
                node_values[slot, 16] = float(b.mean())
                node_values[slot, 17] = _quantile(b, 0.95)
                node_values[slot, 20] = float(p.mean())
                node_values[slot, 21] = _quantile(p, 0.95)
                node_valid[slot, 16:18] = True
                node_valid[slot, 20:22] = True
                if "packet_timing" in caps:
                    d = (seg_last[out_seg] - seg_first[out_seg]) / 1e9
                    ds = np.sort(d)
                    node_values[slot, 29] = float(ds.mean())
                    node_values[slot, 30] = _popvar(d)
                    node_values[slot, 31] = float(ds.max())
                    node_valid[slot, 29:32] = True
            if in_seg.any():
                b = np.sort(seg_bytes[in_seg])
                p = np.sort(seg_count[in_seg].astype(float))
                node_values[slot, 18] = float(b.mean())
                node_values[slot, 19] = _quantile(b, 0.95)
                node_values[slot, 22] = float(p.mean())
                node_values[slot, 23] = _quantile(p, 0.95)
                node_valid[slot, 18:20] = True
                node_valid[slot, 22:24] = True

        # 25: bidirectional byte ratio; healthy idle is a valid 1 (F.6 row 25)
        # External peers carry slots >= n: they contribute to the internal
        # host's aggregates but are never graph nodes (F.7).
        out_bytes = np.zeros(n)
        in_bytes = np.zeros(n)
        src_int = src_slot < n
        dst_int = dst_slot < n
        np.add.at(out_bytes, src_slot[src_int], rows["wire_len"][src_int])
        np.add.at(in_bytes, dst_slot[dst_int], rows["wire_len"][dst_int])
        valid_slots = np.where(obs_valid)[0]
        node_values[valid_slots, 24] = (
            (out_bytes[valid_slots] + 1) / (in_bytes[valid_slots] + 1)
        )
        node_valid[valid_slots, 24] = True

        # 26-29: outgoing IAT seconds, sorted with stable ties (F.6 rows 26-29)
        if "packet_timing" in caps:
            for slot in range(n):
                m = src_slot == slot
                if int(m.sum()) >= 2:
                    t = np.sort(times[m])
                    iat = np.diff(t) / 1e9
                    node_values[slot, 25] = float(iat.mean())
                    node_values[slot, 26] = _popvar(iat)
                    node_values[slot, 27] = float(iat.max())
                    node_values[slot, 28] = float(iat.min())
                    node_valid[slot, 25:29] = True

        # 33-36: TTL / raw TCP window (F.8 reference default: unlogged)
        for slot in range(n):
            m = src_slot == slot
            ttl = rows["ttl"][m]
            ttl_ok = ttl[ttl >= 0]
            if "ip_ttl" in caps and len(ttl_ok) >= 1:
                node_values[slot, 32] = float(ttl_ok.mean())
                node_values[slot, 33] = _popvar(ttl_ok.astype(float))
                node_valid[slot, 32:34] = True
            win = rows["tcp_window"][m]
            win_ok = win[win >= 0]
            if "tcp_window" in caps and len(win_ok) >= 1:
                node_values[slot, 34] = float(win_ok.mean())
                node_values[slot, 35] = _popvar(win_ok.astype(float))
                node_valid[slot, 34:36] = True

        # 37: retransmission heuristic — bounded sequence overlap (F.3)
        if "tcp_sequence" in caps:
            for slot in range(n):
                m = src_slot == slot
                sub = rows[m]
                elig = sub[
                    (sub["proto"] == PROTO_TCP)
                    & (sub["tcp_seq"] >= 0)
                    & (sub["payload_len"] > 0)
                ]
                if len(elig) > 0:
                    starts = (elig["tcp_seq"] % (2**32)).tolist()
                    ends = (
                        elig["tcp_seq"] % (2**32) + elig["payload_len"]
                    ).tolist()
                    retrans = 0
                    seen: list[tuple[int, int]] = []
                    for s, e in zip(starts, ends):
                        if any(not (e <= a or s >= b) for a, b in seen):
                            retrans += 1
                        seen.append((s, e))
                    node_values[slot, 36] = retrans / len(elig)
                    node_valid[slot, 36] = True

        # 38: fragmented fraction
        if "ip_fragmentation" in caps:
            for slot in range(n):
                m = src_slot == slot
                total = int(m.sum())
                if total > 0:
                    node_values[slot, 37] = float(rows["fragmented"][m].sum()) / total
                    node_valid[slot, 37] = True

        # 39-43: payload bins — fractions summing to 1 (F.6 rows 39-43)
        if "transport_payload_length" in caps:
            for slot in range(n):
                m = src_slot == slot
                pl = rows["payload_len"][m]
                pl_ok = pl[pl >= 0]
                if len(pl_ok) > 0:
                    hist = np.zeros(5)
                    edges = PAYLOAD_BINS
                    hist[0] = int((pl_ok < edges[0]).sum())
                    hist[1] = int(((pl_ok >= edges[0]) & (pl_ok < edges[1])).sum())
                    hist[2] = int(((pl_ok >= edges[1]) & (pl_ok < edges[2])).sum())
                    hist[3] = int(((pl_ok >= edges[2]) & (pl_ok < edges[3])).sum())
                    hist[4] = int((pl_ok >= edges[3]).sum())
                    node_values[slot, 38:43] = (hist / hist.sum()).astype(np.float32)
                    node_valid[slot, 38:43] = True

    # ---- edges (F.7): per directed internal pair, aggregated across ports --
    ordered_pairs = sorted(pair_byte.keys())
    edge_index = np.zeros((2, len(ordered_pairs)), dtype=np.int64)
    edge_values = np.zeros((len(ordered_pairs), _N_EDGE), dtype=np.float32)
    edge_valid = np.zeros((len(ordered_pairs), _N_EDGE), dtype=bool)
    evidence = EvidenceIndex()
    for e, (u, v) in enumerate(ordered_pairs):
        edge_index[0, e] = u
        edge_index[1, e] = v
        rws = pair_rows[(u, v)]
        sub = rows[rws]
        total_pkts = len(sub)
        proto = sub["proto"]
        edge_values[e, 0] = float(sub["wire_len"].sum())
        edge_values[e, 1] = float(total_pkts)
        edge_values[e, 2] = float(len(np.unique(inv[rws])))
        if "packet_timing" in caps and len(sub) >= 1:
            edge_values[e, 3] = float((sub["t_ns"].max() - sub["t_ns"].min()) / 1e9)
            edge_valid[e, 3] = True
        f = sub["flags"].astype(np.int64)
        if "tcp_flags" in caps:
            edge_values[e, 4] = int((f & _SYN != 0).sum())
            edge_values[e, 5] = int((f & _RST != 0).sum())
            edge_valid[e, 4] = True
            edge_valid[e, 5] = True
        tcp_f = float((proto == PROTO_TCP).sum()) / total_pkts
        udp_f = float((proto == PROTO_UDP).sum()) / total_pkts
        edge_values[e, 6] = tcp_f
        edge_values[e, 7] = udp_f
        edge_values[e, 8] = 1.0 - tcp_f - udp_f
        reverse = pair_byte.get((v, u))
        uv = float(edge_values[e, 0])
        vu = float(reverse) if reverse is not None else 0.0
        edge_values[e, 9] = (uv - vu) / (uv + vu + 1)
        edge_values[e, 10] = 1.0 if reverse is not None else 0.0
        edge_valid[e, 0] = True
        edge_valid[e, 1] = True
        edge_valid[e, 2] = True
        edge_valid[e, 6:11] = True
        evidence.edge_groups[(u, v)] = rws

    # ---- globals (F.7, exactly 24) ------------------------------------------
    g = np.zeros(_N_GLOBAL, dtype=np.float32)
    gv = np.zeros(_N_GLOBAL, dtype=bool)

    g[0] = flow_starts
    gv[0] = True
    if len(rows):
        active = np.unique(
            np.concatenate([src_slot[src_slot < n], dst_slot[dst_slot < n]])
        )
        g[1] = len(active)
    gv[1] = True

    current_pairs = set(ordered_pairs)
    if w_index > 0:
        # Pair novelty vs past-only context; invalid at the reset boundary
        # (F.7) — window 0 stays masked.
        if current_pairs:
            new = sum(1 for p in current_pairs if p not in seen_pairs)
            g[2] = new / len(current_pairs)
        gv[2] = True
    seen_pairs.update(current_pairs)

    nn = n if n >= 2 else 0
    g[3] = (len(ordered_pairs) / (nn * (nn - 1))) if nn >= 2 else 0.0
    gv[3] = True

    degree = in_deg + out_deg
    nonzero = degree[degree > 0]
    if len(nonzero) > 0:
        counts = np.bincount(nonzero)
        p = counts[counts > 0] / counts.sum()
        if len(p) > 1:
            g[4] = float(-(p * np.log(p)).sum()) / float(np.log(len(p)))
        else:
            g[4] = 0.0
        gv[4] = True
    else:
        g[4] = 0.0  # entirely idle valid graph: explicit zero (F.7)
        gv[4] = True

    if len(rows):
        tcp_all = rows["proto"] == PROTO_TCP
        tcp_count = int(tcp_all.sum())
        if "tcp_flags" in caps and tcp_count > 0:
            for j, bit in enumerate((_SYN, _ACK, _FIN, _RST, _PSH, _URG)):
                g[5 + j] = float((flags[tcp_all] & bit != 0).sum()) / tcp_count
                gv[5 + j] = True
        total = len(rows)
        g[11] = tcp_count / total
        g[12] = float((rows["proto"] == PROTO_UDP).sum()) / total
        g[13] = 1.0 - g[11] - g[12]
        gv[11:14] = True

        if ordered_pairs:
            pb = np.sort(np.array([pair_byte[p] for p in ordered_pairs], dtype=float))
            g[14] = float(pb.mean())
            g[15] = _quantile(pb, 0.50)
            g[16] = _quantile(pb, 0.95)
            g[17] = _quantile(pb, 0.99)
            gv[14:18] = True
            pp = np.sort(np.array([pair_packets[p] for p in ordered_pairs], dtype=float))
            g[18] = float(pp.mean())
            g[19] = _quantile(pp, 0.50)
            g[20] = _quantile(pp, 0.95)
            g[21] = _quantile(pp, 0.99)
            gv[18:22] = True

    gap_hosts = sum(
        1
        for host, intervals in sensor_gaps.items()
        if any(f <= end and t >= start for f, t in intervals)
    )
    g[22] = gap_hosts / n if n else 0.0
    gv[22] = True

    if len(rows):
        lag = (rows["ingested_ns"] - rows["t_ns"]) / 1e9
        lag = lag[lag >= 0]
        if len(lag):
            g[23] = _quantile(np.sort(lag), 0.95)
            gv[23] = True

    for slot in range(n):
        rws = np.where(src_slot == slot)[0].tolist()
        if rws:
            evidence.node_groups[(slot, "traffic")] = rws

    return RawGraphWindow(
        window_start_ns=start,
        window_end_ns=end,
        decision_cutoff_ns=cutoff,
        ordered_entity_ids=entity_ids,
        node_values=node_values,
        node_validity=node_valid,
        edge_index=edge_index,
        edge_values=edge_values,
        edge_validity=edge_valid,
        global_values=g,
        global_validity=gv,
        node_present=np.ones(n, dtype=bool),
        node_observation_valid=obs_valid,
        evidence=evidence,
        feature_registry_hash=registry_hash,
        raw_prefix_hash=prefix_hash,
        window_index=w_index,
    )
