"""Paired synthetic-range trials (Build Spec Section 22, Appendix O).

From one cutoff, the SAME episode (same seed, byte-identical prefix) runs
two continuations:

- no-action: the original scripted campaign;
- action: the ``block_edge`` network restriction takes effect at the action
  time — packets on the blocked pair stop, and chain steps causally
  downstream of a lost C2 channel are suppressed (the scripted attacker
  cannot command those moves without control).

Every measurement is independently computed from the packet tables, never
from the model agreeing with itself (Section 22): attack events
occurred/averted per arm, blocked packet counts, and benign-service
disruption (collateral suppression of non-attack traffic).

Honesty: the synthetic attacker has no backup channel in these campaigns —
adaptive attacker/defender policies are Tier C research (Section 22), and
simulator success is not production proof (Section 2). No real-world
control effect is claimed: execution happens in the disclosed range only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

_NS = 1_000_000_000
MIN = 60 * _NS

#: How long one scripted chain-step behavior occupies its pair (lateral
#: sessions, exploit, exfil runs).
STEP_SPAN_NS = 5 * MIN


@dataclass
class ArmResult:
    label: str                      # "no_action" | "action"
    events: list[dict] = field(default_factory=list)
    benign_bytes_after: int = 0
    packets_after: int = 0
    packets_blocked: int = 0        # action arm only

    def to_json(self) -> dict:
        return {
            "label": self.label,
            "events": self.events,
            "benign_bytes_after": self.benign_bytes_after,
            "packets_after": self.packets_after,
            "packets_blocked": self.packets_blocked,
        }


@dataclass
class RangeTrialResult:
    cutoff_window: int
    action: dict
    no_action: ArmResult
    action_arm: ArmResult
    averted_events: list[dict] = field(default_factory=list)
    service_disruption: dict = field(default_factory=dict)
    postcondition_verified: bool = False

    def to_json(self) -> dict:
        return {
            "cutoff_window": self.cutoff_window,
            "action": self.action,
            "no_action": self.no_action.to_json(),
            "action_arm": self.action_arm.to_json(),
            "averted_events": self.averted_events,
            "service_disruption": self.service_disruption,
            "postcondition_verified": self.postcondition_verified,
            "note": (
                "paired trial in the disclosed synthetic range (same seed, "
                "same prefix, two continuations); the scripted attacker has "
                "no backup channel - adaptive scenarios are Tier C. Not a "
                "production control claim (Sections 2, 22)."
            ),
        }


def _attack_spans(episode) -> list[tuple[str, str, int, int]]:
    """(source, target, from_ns, to_ns) spans of scripted attack behavior —
    used to separate attack traffic from benign traffic when measuring
    collateral disruption."""
    spans: list[tuple[str, str, int, int]] = []
    for step in episode.chain:
        if step.task_index == 3:  # C2 channel runs to the end once open
            spans.append((step.source, step.target, step.time_ns, episode.end_ns))
        elif step.task_index == 4:  # exfil run
            spans.append((step.source, step.target, step.time_ns, step.time_ns + 8 * MIN))
        else:
            spans.append((step.source, step.target, step.time_ns, step.time_ns + STEP_SPAN_NS))
    # Recon/spray stages: the staging entity scans/sprays peers.
    for stage in episode.stages:
        if stage.tactic_index == 0:
            spans.append((stage.entity, "*", stage.from_ns, stage.to_ns))
    return spans


def _in_attack_span(spans, src: str, dst: str, t: int) -> bool:
    for (s, d, f, to) in spans:
        if f <= t <= to and src == s and (d == "*" or d == dst):
            return True
    return False


def _is_attack_packet(spans, names, row) -> bool:
    return _in_attack_span(
        spans, names[int(row["src"])], names[int(row["dst"])], int(row["t_ns"])
    )


def _events_after(episode, action_time_ns: int) -> list[dict]:
    return [
        {
            "task_index": s.task_index,
            "source": s.source,
            "target": s.target,
            "time_ns": str(s.time_ns),
        }
        for s in episode.chain
        if s.time_ns > action_time_ns
    ]


def paired_trial(episode, cutoff_window: int, *, source: str, target: str) -> RangeTrialResult:
    """Run the paired no-action / action continuations from one cutoff."""
    action_time_ns = cutoff_window * 30 * _NS
    table = episode.capture.packets
    names = [h.name for h in episode.capture.hosts]
    spans = _attack_spans(episode)

    src_i, tgt_i = names.index(source), names.index(target)
    on_pair = (
        ((table["src"] == src_i) & (table["dst"] == tgt_i))
        | ((table["src"] == tgt_i) & (table["dst"] == src_i))
    )
    after = table["t_ns"] > action_time_ns

    # Causal suppression: hosts that LOST their C2 channel to the block
    # cannot command later chain steps sourced from them.
    c2_lost = {
        s.source
        for s in episode.chain
        if s.task_index == 3
        and s.time_ns <= action_time_ns
        and {s.source, s.target} == {source, target}
    }
    drop = on_pair & after
    suppressed_steps: set[tuple[str, str, int]] = set()
    disabled_sources = set(c2_lost)
    for step in sorted(episode.chain, key=lambda item: item.time_ns):
        if step.time_ns <= action_time_ns:
            continue
        blocked_step = {step.source, step.target} == {source, target}
        if blocked_step or step.source in disabled_sources:
            suppressed_steps.add((step.source, step.target, step.time_ns))
            s_i, d_i = names.index(step.source), names.index(step.target)
            span = (
                (table["t_ns"] >= step.time_ns)
                & (table["t_ns"] <= step.time_ns + STEP_SPAN_NS)
            )
            drop |= span & (table["src"] == s_i) & (table["dst"] == d_i)
            # A suppressed compromise/lateral step cannot create a source
            # for later actions.  Propagate this through the scripted DAG.
            if step.task_index in (1, 2):
                disabled_sources.add(step.target)

    action_table = table[~drop]

    # ---- measurements -----------------------------------------------------
    after_mask = table["t_ns"] > action_time_ns
    a_after_mask = action_table["t_ns"] > action_time_ns

    def benign_bytes(tbl, mask) -> int:
        total = 0
        for row in tbl[mask]:
            if not _is_attack_packet(spans, names, row):
                total += int(row["wire_len"])
        return total

    no_arm = ArmResult(
        label="no_action",
        events=_events_after(episode, action_time_ns),
        benign_bytes_after=benign_bytes(table, after_mask),
        packets_after=int(after_mask.sum()),
    )

    blocked = int((drop).sum())
    a_events = []
    averted = []
    for ev in no_arm.events:
        key = (ev["source"], ev["target"], int(ev["time_ns"]))
        if key in suppressed_steps:
            averted.append(ev)
        else:
            a_events.append(ev)
    act_arm = ArmResult(
        label="action",
        events=a_events,
        benign_bytes_after=benign_bytes(action_table, a_after_mask),
        packets_after=int(a_after_mask.sum()),
        packets_blocked=blocked,
    )

    collateral = 0
    for row in table[drop]:
        if not _is_attack_packet(spans, names, row):
            collateral += 1

    disruption = {
        "benign_bytes_no_action": no_arm.benign_bytes_after,
        "benign_bytes_action": act_arm.benign_bytes_after,
        "benign_packet_loss_pct": (
            round(
                100.0
                * (no_arm.benign_bytes_after - act_arm.benign_bytes_after)
                / max(no_arm.benign_bytes_after, 1),
                3,
            )
        ),
        "collateral_packets_suppressed": collateral,
        "reversibility": "reversible (temporary network restriction)",
    }

    # Postcondition (Section 23: succeeded requires a verified postcondition):
    # zero surviving packets on the blocked pair after the action time,
    # measured on the ACTION-ARM table (not the original).
    surviving = int(
        (
            (
                ((action_table["src"] == src_i) & (action_table["dst"] == tgt_i))
                | ((action_table["src"] == tgt_i) & (action_table["dst"] == src_i))
            )
            & (action_table["t_ns"] > action_time_ns)
        ).sum()
    )
    postcondition = surviving == 0

    return RangeTrialResult(
        cutoff_window=cutoff_window,
        action={"action_type": "block_edge", "source": source, "target": target},
        no_action=no_arm,
        action_arm=act_arm,
        averted_events=averted,
        service_disruption=disruption,
        postcondition_verified=postcondition,
    )
