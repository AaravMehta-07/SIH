"""Candidate generation for the Tier B path engine (Build Spec Section 20).

The candidate universe at a cutoff is the authorized inventory (all directed
internal pairs) plus every external↔internal pair whose external endpoint
appears in the capture — observed reachable entities, prior communications
and authorized inventory (Section 20). The universe is CANONICAL (sorted),
so every cutoff of a topology shares one option space and batches train
against identical candidate lists.

Pair KINDS record how the prefix currently supports each pair (active /
external_active / inactive_seen / inventory): previously seen but inactive
edges and same-role alternatives stay in the universe as hard negatives —
every pair competes in the decoder softmax at every step, which is stronger
than sampled negatives.

A no-event option (STOP) and an outside-candidate option (OUTSIDE) are
special marks with their own probability mass.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

_NS = 1_000_000_000
WINDOW_NS = 30 * _NS

#: How many 30-second windows back count as "recent" activity.
RECENT_WINDOWS = 8

#: Path time bins: 6 bins of 5 minutes over the 30-minute horizon.
PATH_TIME_BINS = 6
PATH_BIN_SECONDS = 300

#: Special mark kinds (never candidate indices).
STOP = "stop"
OUTSIDE = "outside"
BOS = "bos"


@dataclass(frozen=True)
class MarkOption:
    """One next-mark option: a typed event on a pair in a time bin, or a
    special (STOP / OUTSIDE) token."""

    kind: str                      # "candidate" | "stop" | "outside"
    task_index: int = -1
    source: str = ""
    target: str = ""
    time_bin: int = -1

    def label(self) -> str:
        if self.kind != "candidate":
            return self.kind.upper()
        return f"{self.source} -> {self.target}"


def _eligible_prefix(table: np.ndarray, cutoff_ns: int) -> np.ndarray:
    """Section-7 eligibility: event, availability and ingestion all at or
    before the decision cutoff."""
    return (
        (table["t_ns"] <= cutoff_ns)
        & (table["available_ns"] <= cutoff_ns)
        & (table["ingested_ns"] <= cutoff_ns)
    )


def build_node_names(entity_ids: tuple[str, ...], capture) -> tuple[str, ...]:
    """Path vocabulary: internal scope slots first, then external hosts in
    stable capture order (internal slots index the world-state entity memory;
    externals use a learned bucket embedding)."""
    externals = [h.name for h in capture.hosts if h.role == "external"]
    return tuple(entity_ids) + tuple(externals)


def external_buckets(node_names: tuple[str, ...], internal_count: int) -> list[int]:
    """Stable hash bucket per external node name (16 buckets)."""
    out: list[int] = []
    for name in node_names[internal_count:]:
        h = 2166136261
        for ch in name:
            h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
        out.append(h % 16)
    return out


def canonical_pairs(node_names: tuple[str, ...], internal_count: int) -> tuple[tuple[str, str], ...]:
    """Canonical candidate universe: all directed internal pairs (authorized
    inventory) plus external↔internal pairs for observed externals."""
    internal = list(node_names[:internal_count])
    external = list(node_names[internal_count:])
    pairs = {(a, b) for a in internal for b in internal if a != b}
    for e in external:
        for i in internal:
            pairs.add((e, i))
            pairs.add((i, e))
    return tuple(sorted(pairs))


@dataclass
class CandidateSet:
    """Candidate next-mark universe at one cutoff."""

    cutoff_window: int
    node_names: tuple[str, ...]
    internal_count: int
    pairs: tuple[tuple[str, str], ...]
    pair_kinds: dict[tuple[str, str], str]
    options: tuple[MarkOption, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.options:
            opts: list[MarkOption] = []
            for (src, tgt) in self.pairs:
                for task in range(5):
                    for b in range(PATH_TIME_BINS):
                        opts.append(
                            MarkOption("candidate", task, src, tgt, b)
                        )
            opts.append(MarkOption(STOP))
            opts.append(MarkOption(OUTSIDE))
            self.options = tuple(opts)

    @property
    def pair_count(self) -> int:
        return len(self.pairs)

    def option_index(self, task: int, source: str, target: str, bin_: int) -> int:
        """Index of one candidate option; -1 when the pair is absent."""
        try:
            p = self.pairs.index((source, target))
        except ValueError:
            return -1
        return (p * 5 + task) * PATH_TIME_BINS + bin_

    @property
    def stop_index(self) -> int:
        return len(self.pairs) * 5 * PATH_TIME_BINS

    @property
    def outside_index(self) -> int:
        return self.stop_index + 1

    def to_json(self) -> dict:
        return {
            "cutoff_window": self.cutoff_window,
            "pair_count": len(self.pairs),
            "kinds": {
                kind: sum(1 for v in self.pair_kinds.values() if v == kind)
                for kind in ("active", "external_active", "inactive_seen", "inventory")
            },
        }


def build_candidate_set(
    episode, cutoff_window: int, *, recent_windows: int = RECENT_WINDOWS
) -> CandidateSet:
    """Canonical candidate universe at one cutoff, with per-pair prefix
    support kinds for disclosure."""
    cutoff_ns = cutoff_window * WINDOW_NS
    table = episode.capture.packets
    names = [h.name for h in episode.capture.hosts]
    node_names = build_node_names(episode.internal_entity_ids(), episode.capture)
    roles = {h.name: h.role for h in episode.capture.hosts}
    internal_count = len(node_names) - len(
        [h for h in episode.capture.hosts if h.role == "external"]
    )

    mask = _eligible_prefix(table, cutoff_ns)
    rows = np.where(mask)[0]
    recent_from_ns = (cutoff_window - recent_windows) * WINDOW_NS

    active: set[tuple[str, str]] = set()
    seen: set[tuple[str, str]] = set()
    for r in rows:
        pair = (names[int(table["src"][r])], names[int(table["dst"][r])])
        seen.add(pair)
        if int(table["t_ns"][r]) > recent_from_ns:
            active.add(pair)

    def kind(pair: tuple[str, str]) -> str:
        s_ext = roles[pair[0]] == "external"
        t_ext = roles[pair[1]] == "external"
        if pair in active:
            return "external_active" if (s_ext or t_ext) else "active"
        if pair in seen:
            return "inactive_seen"
        return "inventory"

    pairs = canonical_pairs(node_names, internal_count)
    kinds = {pair: kind(pair) for pair in pairs}
    return CandidateSet(
        cutoff_window=cutoff_window,
        node_names=node_names,
        internal_count=internal_count,
        pairs=pairs,
        pair_kinds=kinds,
    )


def chain_marks_after_cutoff(
    episode, cutoff_window: int, *, horizon_windows: int = 60
) -> list[dict]:
    """Ground-truth chain steps inside the horizon after a cutoff, as coarse
    path bins. Label-side only (N.2 training sequences)."""
    cutoff_ns = cutoff_window * WINDOW_NS
    horizon_ns = (cutoff_window + horizon_windows) * WINDOW_NS
    marks: list[dict] = []
    for step in episode.chain:
        if cutoff_ns < step.time_ns <= horizon_ns:
            rel = step.time_ns - cutoff_ns
            bin_ = min(int(rel // (PATH_BIN_SECONDS * _NS)), PATH_TIME_BINS - 1)
            marks.append(
                {
                    "task_index": step.task_index,
                    "source": step.source,
                    "target": step.target,
                    "time_bin": bin_,
                    "time_ns": step.time_ns,
                    "label_tier": step.label_tier,
                }
            )
    marks.sort(key=lambda m: m["time_ns"])
    return marks


def candidate_recall(
    episode, cutoff_window: int, candidates: CandidateSet
) -> dict:
    """N.2: measure candidate recall before judging the neural ranker —
    the fraction of in-horizon chain steps whose (source, target) pair is in
    the candidate set."""
    marks = chain_marks_after_cutoff(episode, cutoff_window)
    if not marks:
        return {"cutoff_window": cutoff_window, "marks": 0, "recall": None}
    in_set = sum(
        1
        for m in marks
        if (m["source"], m["target"]) in candidates.pair_kinds
    )
    return {
        "cutoff_window": cutoff_window,
        "marks": len(marks),
        "recall": in_set / len(marks),
    }
