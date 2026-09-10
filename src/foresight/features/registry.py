"""The exact feature registry (Build Spec Section 10, F.6, F.7, CT02).

Order is frozen: 44 node values, 11 edge values, 24 global values. A mismatch
blocks artifact load (CT02). One transform per value column, no runtime
inference (F.8): ``log1p`` for nonnegative unbounded counts, durations,
variances and ratios; identity for bounded fractions, normalized entropy and
signed balance. TTL and raw TCP window stay unlogged before robust scaling
(F.8 reference default).
"""

from __future__ import annotations

LOG1P = "log1p"
IDENTITY = "identity"

#: Section 10 node positions 1-44, in order. Comments cite F.6 rows.
NODE_FEATURE_NAMES: tuple[str, ...] = (
    "syn_count",                     # 1
    "ack_count",                     # 2
    "fin_count",                     # 3
    "rst_count",                     # 4
    "psh_count",                     # 5
    "urg_count",                     # 6
    "syn_ack_ratio",                 # 7
    "rst_fraction",                  # 8
    "failed_connection_fraction",    # 9
    "unique_destination_count",      # 10
    "unique_destination_port_count", # 11
    "destination_port_entropy",      # 12
    "contiguous_port_coverage",      # 13
    "in_degree",                     # 14
    "out_degree",                    # 15
    "degree_ratio",                  # 16
    "bytes_sent_mean",               # 17
    "bytes_sent_p95",                # 18
    "bytes_received_mean",           # 19
    "bytes_received_p95",            # 20
    "packets_sent_mean",             # 21
    "packets_sent_p95",              # 22
    "packets_received_mean",         # 23
    "packets_received_p95",          # 24
    "bidirectional_byte_ratio",      # 25
    "iat_mean",                      # 26
    "iat_variance",                  # 27
    "iat_max",                       # 28
    "iat_min",                       # 29
    "duration_mean",                 # 30
    "duration_variance",             # 31
    "duration_max",                  # 32
    "ttl_mean",                      # 33
    "ttl_variance",                  # 34
    "tcp_window_mean",               # 35
    "tcp_window_variance",           # 36
    "retransmission_fraction",       # 37
    "fragmented_packet_fraction",    # 38
    "payload_bin_0",                 # 39
    "payload_bin_1",                 # 40
    "payload_bin_2",                 # 41
    "payload_bin_3",                 # 42
    "payload_bin_4",                 # 43
    "ordered_port_arrival_score",    # 44
)

#: F.7 edge order.
EDGE_FEATURE_NAMES: tuple[str, ...] = (
    "bytes",                   # 1
    "packets",                 # 2
    "flow_count",              # 3 distinct contributing segments
    "duration_mean",           # 4
    "syn_count",               # 5
    "rst_count",               # 6
    "tcp_fraction",            # 7
    "udp_fraction",            # 8
    "other_fraction",          # 9
    "directional_balance",     # 10
    "bilateral_seen",          # 11
)

#: F.7 global order (exactly 24).
GLOBAL_FEATURE_NAMES: tuple[str, ...] = (
    "flow_start_count",            # 1
    "active_host_count",           # 2
    "new_pair_fraction",           # 3
    "density",                     # 4
    "degree_entropy",              # 5
    "flag_fraction_syn",           # 6
    "flag_fraction_ack",           # 7
    "flag_fraction_fin",           # 8
    "flag_fraction_rst",           # 9
    "flag_fraction_psh",           # 10
    "flag_fraction_urg",           # 11
    "tcp_fraction",                # 12
    "udp_fraction",                # 13
    "other_fraction",              # 14
    "pair_bytes_mean",             # 15
    "pair_bytes_p50",              # 16
    "pair_bytes_p95",              # 17
    "pair_bytes_p99",              # 18
    "pair_packets_mean",           # 19
    "pair_packets_p50",            # 20
    "pair_packets_p95",            # 21
    "pair_packets_p99",            # 22
    "missing_packet_channel_fraction",  # 23
    "sensor_lag_p95_seconds",      # 24
)

_NODE_TRANSFORMS: tuple[str, ...] = (
    LOG1P, LOG1P, LOG1P, LOG1P, LOG1P, LOG1P,          # 1-6 counts
    LOG1P,                                              # 7 ratio
    IDENTITY, IDENTITY,                                 # 8-9 fractions
    LOG1P, LOG1P,                                       # 10-11 counts
    IDENTITY, IDENTITY,                                 # 12-13 entropy/coverage
    LOG1P, LOG1P, LOG1P,                                # 14-16 degrees/ratio
    LOG1P, LOG1P, LOG1P, LOG1P,                         # 17-20 bytes
    LOG1P, LOG1P, LOG1P, LOG1P,                         # 21-24 packets
    LOG1P,                                              # 25 ratio
    LOG1P, LOG1P, LOG1P, LOG1P,                         # 26-29 iat
    LOG1P, LOG1P, LOG1P,                                # 30-32 duration
    IDENTITY, IDENTITY,                                 # 33-34 ttl (F.8 default)
    IDENTITY, IDENTITY,                                 # 35-36 raw window
    IDENTITY, IDENTITY,                                 # 37-38 fractions
    IDENTITY, IDENTITY, IDENTITY, IDENTITY, IDENTITY,   # 39-43 payload bins
    IDENTITY,                                           # 44 port arrival
)

_EDGE_TRANSFORMS: tuple[str, ...] = (
    LOG1P, LOG1P, LOG1P, LOG1P, LOG1P, LOG1P,           # bytes/pkts/flows/dur/syn/rst
    IDENTITY, IDENTITY, IDENTITY, IDENTITY, IDENTITY,   # fractions/balance/bilateral
)

_GLOBAL_TRANSFORMS: tuple[str, ...] = (
    LOG1P, LOG1P,                                       # 1-2 counts
    IDENTITY, IDENTITY, IDENTITY,                       # 3-5 fractions/entropy
    IDENTITY, IDENTITY, IDENTITY, IDENTITY, IDENTITY, IDENTITY,  # 6-11 flag fracs
    IDENTITY, IDENTITY, IDENTITY,                       # 12-14 protocol fracs
    LOG1P, LOG1P, LOG1P, LOG1P,                         # 15-18 pair bytes
    LOG1P, LOG1P, LOG1P, LOG1P,                         # 19-22 pair packets
    IDENTITY,                                           # 23 missing channel
    LOG1P,                                              # 24 sensor lag seconds
)

TRANSFORMS = {
    "node": _NODE_TRANSFORMS,
    "edge": _EDGE_TRANSFORMS,
    "global": _GLOBAL_TRANSFORMS,
}

assert len(NODE_FEATURE_NAMES) == 44 and len(_NODE_TRANSFORMS) == 44
assert len(EDGE_FEATURE_NAMES) == 11 and len(_EDGE_TRANSFORMS) == 11
assert len(GLOBAL_FEATURE_NAMES) == 24 and len(_GLOBAL_TRANSFORMS) == 24

#: F.6 payload bins: [0,64), [64,128), [128,512), [512,1024), [1024,inf)
PAYLOAD_BINS = (64, 128, 512, 1024)


def _index_of(names: tuple[str, ...], name: str) -> int:
    return names.index(name)


def node_transform_of(name: str) -> str:
    return _NODE_TRANSFORMS[_index_of(NODE_FEATURE_NAMES, name)]


def edge_transform_of(name: str) -> str:
    return _EDGE_TRANSFORMS[_index_of(EDGE_FEATURE_NAMES, name)]


def global_transform_of(name: str) -> str:
    return _GLOBAL_TRANSFORMS[_index_of(GLOBAL_FEATURE_NAMES, name)]
