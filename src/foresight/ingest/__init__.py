"""Ingestion: normalization, flow segmentation and source adapters (Appendix F).

``normalize`` (Appendix S) turns a RawObject into a canonical event stream
plus quality/capability reports. Packet-derived features are prefix-safe:
segments contribute only their per-window observed deltas (F.2).
"""

from .normalizer import EventStream, NormalizedSession, normalize_events
from .ctu_adapter import CtuLabel, CtuParseResult, classify_ctu_label, iter_ctu_events, parse_ctu_binetflow
from .pcap_adapter import parse_pcap, pcap_event_at
from .segmentation import (
    FLOW_DEFAULTS,
    FlowSegment,
    SegmentAccumulator,
    TcpAttemptTracker,
    segment_packets,
)
from .synthetic import (
    BehaviorPlan,
    SyntheticCapture,
    generate_capture,
)

__all__ = [
    "EventStream",
    "CtuLabel",
    "CtuParseResult",
    "classify_ctu_label",
    "iter_ctu_events",
    "parse_ctu_binetflow",
    "parse_pcap",
    "pcap_event_at",
    "NormalizedSession",
    "normalize_events",
    "FLOW_DEFAULTS",
    "FlowSegment",
    "SegmentAccumulator",
    "TcpAttemptTracker",
    "segment_packets",
    "BehaviorPlan",
    "SyntheticCapture",
    "generate_capture",
]
