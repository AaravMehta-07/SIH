"""CTU-13 scenario-to-episode bridge (Sections 6-11, M.1).

Each episode is one deterministic 55-minute replay slice and one fixed /25
address partition.  The partition is a declared topology rule, not selected
by traffic volume or labels.  Addresses outside the chosen partition remain
external context and never become device identities.
"""

from __future__ import annotations

import ipaddress

import numpy as np

from ..ingest.ctu_adapter import CtuParseResult
from ..ingest.synthetic import GroundTruth, Host, SyntheticCapture
from ..features.windows import FULL_PACKET_CAPABILITIES
from ..ingest.normalizer import EventStream
from .episodes import EPISODE_DURATION_NS, Episode

_NS = 1_000_000_000
_WINDOW_NS = 30 * _NS

CTU_FLOW_CAPABILITIES = frozenset(
    {"ip_addresses", "transport_ports", "flow_lifecycle", "flow_start_time"}
)


def _in_partition(address: str, partition: int) -> bool:
    ip = ipaddress.ip_address(address)
    if not isinstance(ip, ipaddress.IPv4Address) or ip not in ipaddress.ip_network("147.32.84.0/24"):
        return False
    return (int(ip) & 0xFF) // 128 == partition


def build_ctu_episode(
    parsed: CtuParseResult,
    *,
    partition: int = 1,
    slice_index: int = 0,
) -> Episode:
    """Build one fixed-grid real-data episode from a qualified parse result."""

    if partition not in (0, 1) or slice_index < 0:
        raise ValueError("partition must be 0/1 and slice_index nonnegative")
    table = parsed.stream.packet_table
    if table is None or len(table) == 0:
        raise ValueError("CTU scenario has no accepted flow rows")
    absolute_start = (int(table["t_ns"].min()) // _WINDOW_NS) * _WINDOW_NS
    slice_start = absolute_start + slice_index * EPISODE_DURATION_NS
    slice_end = slice_start + EPISODE_DURATION_NS
    if int(table["t_ns"].max()) < slice_end:
        raise ValueError("requested CTU replay slice lacks complete future coverage")
    keep = (table["t_ns"] > slice_start) & (table["t_ns"] <= slice_end)
    selected = table[keep].copy()
    if len(selected) == 0:
        raise ValueError("requested CTU replay slice is empty")
    for field in ("t_ns", "available_ns", "ingested_ns"):
        selected[field] -= slice_start

    raw_hosts = [value.removeprefix("addr:") for value in parsed.stream.notes["hosts"]]
    hosts = tuple(
        Host(
            name=f"addr:{address}",
            role=("ctu-address-scope" if _in_partition(address, partition) else "external"),
            address=address,
            ttl=64,
            tcp_window=65535,
        )
        for address in raw_hosts
    )
    first_events: dict[tuple[str, int], int] = {}
    normal_entities: set[str] = set()
    for label in parsed.labels:
        if label.category == "normal":
            address = label.entity_id.removeprefix("addr:")
            if _in_partition(address, partition):
                normal_entities.add(label.entity_id)
        if not label.task_indices:
            continue
        address = label.entity_id.removeprefix("addr:")
        if not _in_partition(address, partition):
            continue
        relative = label.event_time_ns - slice_start
        if relative <= EPISODE_DURATION_NS:
            for task_index in label.task_indices:
                key = (label.entity_id, task_index)
                first_events[key] = min(first_events.get(key, relative), relative)
    truth = tuple(
        GroundTruth(
            entity=entity,
            task_index=task_index,
            event_time_ns=at,
            label_tier=("weak_proxy" if task_index == 0 else "confirmed"),
            status="observed",
        )
        for (entity, task_index), at in sorted(first_events.items())
    )
    capture = SyntheticCapture(
        capture_id=f"ctu13-{parsed.scenario_id}-p{partition}-s{slice_index}",
        hosts=hosts,
        packets=selected,
        ground_truth=truth,
        start_ns=0,
        end_ns=EPISODE_DURATION_NS,
        sensor_gaps=(),
        campaign=f"ctu13-scenario-{parsed.scenario_id}",
        family="ctu13-real-flow",
        seed=0,
        synthetic=False,
        capabilities=CTU_FLOW_CAPABILITIES,
        capability_report=parsed.stream.capability,
        quality_report=parsed.stream.quality,
        source_disclosure=(
            "real CTU-13 labeled bidirectional flow replay; packet-only fields "
            "unsupported; Background excluded from benign negatives"
        ),
    )
    return Episode(
        episode_id=capture.capture_id,
        campaign=capture.campaign,
        family=capture.family,
        seed=0,
        capture=capture,
        stages=(),
        start_ns=0,
        end_ns=EPISODE_DURATION_NS,
        duration_ns=EPISODE_DURATION_NS,
        chain=(),
        qualified_tasks=(0, 3),
        qualified_tactics=(),
        at_risk_entities_by_task={
            0: frozenset(normal_entities | {entity for entity, _task in first_events}),
            3: frozenset(
                normal_entities
                | {entity for entity, task in first_events if task == 3}
            ),
        },
    )


def build_ctu_pcap_episode(
    packet_stream: EventStream,
    labels: CtuParseResult,
    *,
    partition: int = 1,
    slice_index: int = 0,
) -> Episode:
    """Join scenario-matched CTU packet headers to evaluator-side labels.

    The public CTU PCAP contains botnet traffic only.  No Normal/Background
    traffic or independent availability clock is implied by this join.
    """

    table = packet_stream.packet_table
    if table is None or len(table) == 0:
        raise ValueError("PCAP has no accepted IPv4 packets")
    absolute_start = (int(table["t_ns"].min()) // _WINDOW_NS) * _WINDOW_NS
    slice_start = absolute_start + slice_index * EPISODE_DURATION_NS
    slice_end = slice_start + EPISODE_DURATION_NS
    if int(table["t_ns"].max()) < slice_end:
        raise ValueError("requested PCAP replay slice lacks complete future coverage")
    keep = (table["t_ns"] > slice_start) & (table["t_ns"] <= slice_end)
    selected = table[keep].copy()
    if len(selected) == 0:
        raise ValueError("requested PCAP replay slice is empty")
    for field in ("t_ns", "available_ns", "ingested_ns"):
        selected[field] -= slice_start
    raw_hosts = [value.removeprefix("addr:") for value in packet_stream.notes["hosts"]]
    hosts = tuple(
        Host(
            name=f"addr:{address}",
            role=("ctu-address-scope" if _in_partition(address, partition) else "external"),
            address=address,
        )
        for address in raw_hosts
    )
    first_events: dict[tuple[str, int], int] = {}
    observed_addresses = {f"addr:{address}" for address in raw_hosts}
    for label in labels.labels:
        if label.entity_id not in observed_addresses or not label.task_indices:
            continue
        address = label.entity_id.removeprefix("addr:")
        if not _in_partition(address, partition):
            continue
        relative = label.event_time_ns - slice_start
        if relative <= EPISODE_DURATION_NS:
            for task in label.task_indices:
                key = (label.entity_id, task)
                first_events[key] = min(first_events.get(key, relative), relative)
    truth = tuple(
        GroundTruth(
            entity=entity,
            task_index=task,
            event_time_ns=at,
            label_tier="weak_proxy" if task == 0 else "confirmed",
        )
        for (entity, task), at in sorted(first_events.items())
    )
    capture = SyntheticCapture(
        capture_id=f"ctu13-{labels.scenario_id}-pcap-p{partition}-s{slice_index}",
        hosts=hosts,
        packets=selected,
        ground_truth=truth,
        start_ns=0,
        end_ns=EPISODE_DURATION_NS,
        sensor_gaps=(),
        campaign=f"ctu13-scenario-{labels.scenario_id}-pcap",
        family="ctu13-real-pcap",
        seed=0,
        synthetic=False,
        capabilities=FULL_PACKET_CAPABILITIES,
        capability_report=packet_stream.capability,
        quality_report=packet_stream.quality,
        source_disclosure=(
            "real CTU-13 public botnet-only PCAP; packet headers observed and "
            "flow features derived; not the unavailable full mixed capture"
        ),
    )
    at_risk = frozenset(entity for entity, _task in first_events)
    return Episode(
        episode_id=capture.capture_id,
        campaign=capture.campaign,
        family=capture.family,
        seed=0,
        capture=capture,
        stages=(),
        start_ns=0,
        end_ns=EPISODE_DURATION_NS,
        duration_ns=EPISODE_DURATION_NS,
        chain=(),
        qualified_tasks=(0, 3),
        qualified_tactics=(),
        at_risk_entities_by_task={0: at_risk, 3: at_risk},
    )
