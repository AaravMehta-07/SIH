"""Data-pipeline contract tests (Build Spec Appendix R.1, F.5, F.6).

The R.1 fixture is hand-computed: three synthetic hosts A, B, C over two
30-second windows with every packet's time, flags, sizes and clocks spelled
out in the fixture itself. Expected feature values are derived here by hand
(not by calling the aggregation under test), which is the R.1 requirement.
"""

from __future__ import annotations

import numpy as np
import pytest

from foresight.contracts.canonical import canonical_json
from foresight.data.episodes import Episode, build_episode
from foresight.features.windows import (
    WINDOW_SECONDS,
    build_clip_windows,
    window_bounds,
)
from foresight.ingest.synthetic import PROTO_TCP, PROTO_UDP, finalize_table, flags

NS = 1_000_000_000
S = NS


def packet(t, src, dst, *, proto=PROTO_TCP, sport, dport, flg=0,
           wire=60, payload=0, avail_delay=0.05 * NS, ingest_delay=None):
    available = t + avail_delay
    ingest = ingest_delay if ingest_delay is not None else available
    return (
        t, available, ingest, src, dst, sport, dport, proto, flg,
        wire, payload, 64, 65535, 1000 + int(t // NS), 0,
    )


A, B, C = 0, 1, 2
ENTITIES = ("A.corp.local", "B.corp.local", "C.corp.local")


def r1_table():
    """R.1 fixture: window 1 (0,30s] has A<->B on port 80 plus an unanswered
    A->C SYN; window 2 (30,60s] has a B->C UDP packet and a delayed A->B
    record whose receipt (65 s) is after the 60 s cutoff (TM02)."""
    rows = [
        # A <-> B established exchange on port 80
        packet(1.00 * S, A, B, sport=40000, dport=80, flg=flags(syn=True), wire=60),
        packet(1.01 * S, B, A, sport=80, dport=40000, flg=flags(syn=True, ack=True), wire=60),
        packet(1.02 * S, A, B, sport=40000, dport=80, flg=flags(ack=True), wire=52),
        packet(1.03 * S, A, B, sport=40000, dport=80, flg=flags(ack=True, psh=True), wire=452, payload=400),
        packet(1.04 * S, B, A, sport=80, dport=40000, flg=flags(ack=True, psh=True), wire=1252, payload=1200),
        # A -> C unanswered SYN (pending attempt; no reverse traffic = no
        # bidirectional coverage, so the attempt can never classify)
        packet(2.00 * S, A, C, sport=40001, dport=22, flg=flags(syn=True), wire=60),
        # window 2: healthy B -> C UDP
        packet(31.0 * S, B, C, proto=PROTO_UDP, sport=53000, dport=53, wire=100, payload=48),
        # delayed record: event time 31.5 s, receipt 65 s (TM02)
        packet(31.5 * S, A, B, sport=40002, dport=80, flg=flags(ack=True, psh=True),
               wire=452, payload=400, ingest_delay=65 * S),
    ]
    return finalize_table(rows)


def build_windows(table, cutoff_ns, history=2):
    entity_of_host = {A: 0, B: 1, C: 2}
    return build_clip_windows(
        table,
        entity_ids=ENTITIES,
        entity_of_host=entity_of_host,
        internal_hosts={A, B, C},
        cutoff_ns=cutoff_ns,
        history_windows=history,
    )


class TestWindowGrid:
    """TM05: a packet exactly on a boundary belongs to the preceding window."""

    def test_boundary_packet_in_preceding_window(self):
        rows = [
            packet(30 * S, A, B, sport=1, dport=80, flg=flags(syn=True)),
        ]
        table = finalize_table(rows)
        windows = build_windows(table, cutoff_ns=60 * S)
        # window (0,30] must contain the packet; window (30,60] must not
        assert windows[0].node_values[0, 0] == 1  # A syn_count
        assert windows[1].node_values[0, 0] == 0

    def test_window_bounds_ordering(self):
        bounds = window_bounds(60 * S, 2)
        assert bounds == [(0, 30 * S), (30 * S, 60 * S)]


class TestEligibility:
    """TM02: event before d but receipt after d is excluded."""

    def test_delayed_receipt_excluded_then_included(self):
        table = r1_table()
        # cutoff 60 s: the delayed record (ingest 65 s) is ineligible
        windows = build_windows(table, cutoff_ns=60 * S)
        w2 = windows[1]
        # A is healthy idle in window 2 (valid zeros, FE02)
        assert w2.node_values[0, 0] == 0 and w2.node_validity[0, 0]
        assert w2.node_values[0, 24] == 1  # bidirectional ratio idle = 1
        # cutoff 90 s: the same window recomputed now includes the packet.
        # The 2-window clip ending at 90 s is [(30,60], (60,90]] — the
        # recomputed (30,60] window is index 0.
        windows90 = build_clip_windows(
            table, entity_ids=ENTITIES, entity_of_host={A: 0, B: 1, C: 2},
            internal_hosts={A, B, C}, cutoff_ns=90 * S, history_windows=2,
        )
        w2_later = windows90[0]
        assert w2_later.node_values[0, 0] == 0  # no SYN in the delayed packet
        assert w2_later.node_values[0, 4] == 1  # PSH count now 1
        # byte mean now reflects the 452-byte segment
        assert w2_later.node_values[0, 16] == 452


class TestHandComputedFeatures:
    """FE01: hand-computed aggregation for host A, window 1 of the R.1
    fixture. Every expected value below was derived by hand from the packet
    list, not from the implementation."""

    @pytest.fixture()
    def w1(self):
        return build_windows(r1_table(), cutoff_ns=60 * S)[0]

    def test_flag_counts(self, w1):
        # A outgoing: SYN->B, ACK->B, PSH+ACK->B, SYN->C
        assert w1.node_values[0, 0] == 2  # syn_count
        assert w1.node_values[0, 1] == 2  # ack_count
        assert w1.node_values[0, 4] == 1  # psh_count
        assert w1.node_validity[0, 0:6].all()

    def test_flag_ratios(self, w1):
        assert w1.node_values[0, 6] == pytest.approx(2 / 3)  # syn/(ack+1)
        assert w1.node_values[0, 7] == 0.0  # rst fraction

    def test_pending_attempt_masked_when_no_coverage(self, w1):
        # FE03: the A->C SYN has no bidirectional coverage: it stays pending.
        # A's one matured attempt (A->B, SYN/ACK handshake) is a success, so
        # the failure fraction is a VALID zero — the pending attempt adds no
        # failure label (F.3: pending stays pending).
        assert w1.node_validity[0, 8]
        assert w1.node_values[0, 8] == 0.0

    def test_destination_features(self, w1):
        assert w1.node_values[0, 9] == 2  # distinct destinations: B, C
        assert w1.node_values[0, 10] == 2  # distinct ports: 80, 22
        # entropy: packets by port = [3 (80), 1 (22)]
        p = np.array([3 / 4, 1 / 4])
        expected_h = float(-(p * np.log(p)).sum()) / np.log(2)
        assert w1.node_values[0, 11] == pytest.approx(expected_h)
        # contiguous coverage: |80-22| != 1 -> 0
        assert w1.node_values[0, 12] == 0.0

    def test_degrees(self, w1):
        assert w1.node_values[0, 13] == 1  # in: B->A
        assert w1.node_values[0, 14] == 2  # out: B, C
        assert w1.node_values[0, 15] == pytest.approx(3 / 2)

    def test_segment_volume(self, w1):
        # A->B segment bytes: 60+52+452=564 ; A->C: 60 -> mean 312
        assert w1.node_values[0, 16] == pytest.approx(312.0)
        # p95 over [60, 564]: interpolate r=0.95 -> 60*0.05+564*0.95
        assert w1.node_values[0, 17] == pytest.approx(564 * 0.95 + 60 * 0.05)
        # received from B: one segment 60+1252=1312
        assert w1.node_values[0, 18] == pytest.approx(1312.0)
        # packets sent per segment: [3, 1] -> mean 2, p95 ~ 2.8
        assert w1.node_values[0, 20] == pytest.approx(2.0)

    def test_bidirectional_ratio(self, w1):
        # (out 624 + 1) / (in 1312 + 1)
        assert w1.node_values[0, 24] == pytest.approx(625 / 1313)

    def test_iat_statistics(self, w1):
        # A outgoing times: 1.00, 1.02, 1.03, 2.00 -> iats 0.02, 0.01, 0.97
        iats = np.array([0.02, 0.01, 0.97])
        assert w1.node_values[0, 25] == pytest.approx(float(iats.mean()), abs=1e-5)
        assert w1.node_values[0, 26] == pytest.approx(float(iats.var()), abs=1e-5)
        assert w1.node_values[0, 27] == pytest.approx(0.97, abs=1e-5)
        assert w1.node_values[0, 28] == pytest.approx(0.01, abs=1e-5)

    def test_payload_bins(self, w1):
        # payload lengths of A's outgoing: 0, 0, 400, 0
        expected = [0.75, 0.0, 0.25, 0.0, 0.0]
        assert list(w1.node_values[0, 38:43]) == pytest.approx(expected)

    def test_edge_features(self, w1):
        # A->B edge: bytes 564, packets 3, one segment, syn 1
        found = None
        for e in range(w1.edge_index.shape[1]):
            if (int(w1.edge_index[0, e]), int(w1.edge_index[1, e])) == (0, 1):
                found = e
        assert found is not None
        assert w1.edge_values[found, 0] == 564
        assert w1.edge_values[found, 1] == 3
        assert w1.edge_values[found, 2] == 1  # one contributing segment
        assert w1.edge_values[found, 4] == 1  # syn count
        # directional balance (564-1312)/(564+1312+1)
        assert w1.edge_values[found, 9] == pytest.approx((564 - 1312) / 1877)
        assert w1.edge_values[found, 10] == 1  # bilateral seen

    def test_healthy_idle_vs_missing(self, w1):
        """FE02: healthy idle counts are valid zeros. Host C in window 2
        receives one UDP packet (valid); a sensor gap would mask everything."""
        table = r1_table()
        windows = build_windows(table, cutoff_ns=60 * S)
        w2 = windows[1]
        # C in window 2: received the UDP packet -> in_degree 1
        assert w2.node_values[2, 13] == 1
        # A in window 2: healthy idle -> valid zero syn count (not masked)
        assert w2.node_values[0, 0] == 0 and w2.node_validity[0, 0]


class TestSegmentation:
    """FE04: long-flow lifetime bytes are not repeated in each window."""

    def test_per_window_deltas(self):
        # one A->B flow spanning two windows with per-window packets
        rows = [
            packet(10 * S, A, B, sport=1, dport=80, flg=flags(ack=True, psh=True), wire=100),
            packet(40 * S, A, B, sport=1, dport=80, flg=flags(ack=True, psh=True), wire=200),
        ]
        table = finalize_table(rows)
        windows = build_windows(table, cutoff_ns=60 * S)
        # window 1 edge bytes = 100 only; window 2 = 200 only (never 300)
        assert windows[0].edge_values[0, 0] == 100
        assert windows[1].edge_values[0, 0] == 200

    def test_duplicate_syns_one_attempt(self):
        """FE03: duplicate SYN retransmissions do not multiply attempts."""
        rows = [
            packet(1.0 * S, A, C, sport=1, dport=22, flg=flags(syn=True)),
            packet(1.5 * S, A, C, sport=1, dport=22, flg=flags(syn=True)),
            packet(2.0 * S, A, C, sport=1, dport=22, flg=flags(syn=True)),
        ]
        table = finalize_table(rows)
        windows = build_windows(table, cutoff_ns=60 * S)
        # 3 SYNs on the wire but they are one attempt: no coverage for (A,C)
        # keeps it pending -> masked; the SYN count itself is still 3.
        assert windows[0].node_values[0, 0] == 3
        assert not windows[0].node_validity[0, 8]

    def test_rst_classifies_failure(self):
        """An observed RST from the responder classifies the attempt failed."""
        rows = [
            packet(1.0 * S, A, C, sport=1, dport=22, flg=flags(syn=True)),
            packet(1.05 * S, C, A, sport=22, dport=1, flg=flags(rst=True, ack=True)),
        ]
        table = finalize_table(rows)
        windows = build_windows(table, cutoff_ns=60 * S)
        assert windows[0].node_values[0, 8] == 1.0
        assert windows[0].node_validity[0, 8]


class TestCanonicalJSON:
    """CT01: nonfinite values and unorderable content are rejected."""

    def test_rejects_nan(self):
        with pytest.raises(Exception):
            canonical_json({"x": float("nan")})

    def test_rejects_infinity(self):
        with pytest.raises(Exception):
            canonical_json({"x": float("inf")})

    def test_deterministic_key_order(self):
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        assert a == b

    def test_negative_zero_normalized(self):
        assert canonical_json({"x": -0.0}) == canonical_json({"x": 0.0})


class TestEpisodeCorpus:
    """Determinism and label structure of the synthetic corpus."""

    def test_deterministic_generation(self):
        e1 = build_episode("web-to-lateral", 0, seed=99)
        e2 = build_episode("web-to-lateral", 0, seed=99)
        assert len(e1.capture.packets) == len(e2.capture.packets)
        assert np.array_equal(e1.capture.packets["t_ns"], e2.capture.packets["t_ns"])

    def test_episode_labels_and_stages(self):
        ep = build_episode("web-to-lateral", 0, seed=42)
        assert any(g.task_index == 1 for g in ep.ground_truth)  # initial access
        assert any(g.task_index == 2 for g in ep.ground_truth)  # lateral
        assert ep.stages, "stage windows must exist for tactic tags"
        internal = ep.internal_entity_ids()
        assert all(n.endswith((".corp.local", ".dmz.local")) for n in internal)

    def test_as_episode_object(self):
        ep: Episode = build_episode("c2-exfil", 0, seed=7)
        assert ep.family == "c2-exfil"
        assert ep.end_ns == 110 * 30 * NS
