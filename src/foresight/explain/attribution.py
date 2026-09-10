"""Grouped-deletion attribution for a selected forecast target (K.1).

Perturbation semantics: deleting a communication group removes its packets
from the prefix and recomputes the affected window features — the entity
reads as healthy-idle for that window, which is the physically meaningful
"this traffic never happened" counterfactual. Derived counts and ratios stay
coherent because features are recomputed, not edited (K.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch

from ..data.clips import EpisodePrecomputed
from ..data.episodes import Episode
from ..features.transforms import FeatureScaler
from ..features.windows import build_clip_windows
from ..graphs.collate import collate_windows
from ..labels.targets import all_pair_candidates
from ..runtime.forecast import ForecastEngine, ForecastRequest

_NS = 1_000_000_000
WINDOW_NS = 30 * _NS
HISTORY_WINDOWS = 20


@dataclass(frozen=True)
class AttributionBudget:
    """Declared compute budget (K.1). Attribution beyond the budget is
    reported as partial rather than silently truncated."""

    max_groups: int = 20
    random_controls: int = 8
    top_k_evidence: int = 5


@dataclass(frozen=True)
class EvidenceItem:
    """D.8 evidence item: source-linked, signed, method-tagged."""

    category: str            # "deletion_delta" | "random_control"
    entity: str
    window_index: int
    delta: float             # risk(with group) - risk(group deleted)
    packet_rows: tuple[int, ...]  # legal-prefix packet rows (EX02)
    method: str = "grouped_deletion"

    def to_json(self) -> dict:
        return {
            "category": self.category,
            "entity": self.entity,
            "window_index": self.window_index,
            "delta": self.delta,
            "packet_row_count": len(self.packet_rows),
            "method": self.method,
        }


@dataclass
class ExplanationResult:
    """K.1 output for one (entity, task, horizon) selection."""

    entity: str
    task_index: int
    horizon_bins: int
    baseline_risk: float
    evidence: list[EvidenceItem] = field(default_factory=list)
    comprehensiveness: float | None = None
    sufficiency: float | None = None
    random_baseline_comprehensiveness: float | None = None
    stability: float | None = None
    partial: bool = False
    note: str = "grouped deletion over prefix windows; deltas are sensitivity, not causal effects"

    def to_json(self) -> dict:
        return {
            "entity": self.entity,
            "task_index": self.task_index,
            "horizon_bins": self.horizon_bins,
            "baseline_risk": self.baseline_risk,
            "evidence": [e.to_json() for e in self.evidence],
            "comprehensiveness": self.comprehensiveness,
            "sufficiency": self.sufficiency,
            "random_baseline_comprehensiveness": (
                self.random_baseline_comprehensiveness
            ),
            "partial": self.partial,
            "note": self.note,
        }


def _risk_of(
    engine: ForecastEngine,
    request: ForecastRequest,
    windows: list,
    entity: str,
    entity_ids: tuple[str, ...],
    task_index: int,
) -> float:
    result = engine.forecast(windows, request)
    slot = entity_ids.index(entity)
    for e in result.entities:
        if e.slot != slot:
            continue
        tf = e.task_forecasts[task_index]
        if tf.distribution is None:
            return 0.0
        return float(tf.distribution.cumulative_risk[request.horizon_bins - 1])
    return 0.0


def _build_perturbed(
    episode: Episode,
    pre: EpisodePrecomputed,
    scaler: FeatureScaler,
    cutoff_window: int,
    *,
    delete_host: int | None,
    delete_window: int | None,
    keep_only_windows: set[int] | None = None,
) -> list:
    """Rebuild the 20 prefix windows with packets removed (K.1: remove
    source events, then recompute features)."""
    table = episode.capture.packets
    if delete_host is not None and delete_window is not None:
        start = (delete_window - 1) * WINDOW_NS
        end = delete_window * WINDOW_NS
        in_window = (table["t_ns"] > start) & (table["t_ns"] <= end)
        involves = (table["src"] == delete_host) | (table["dst"] == delete_host)
        keep = ~(in_window & involves)
        filtered = table[keep]
    elif keep_only_windows is not None:
        keep = np.zeros(len(table), dtype=bool)
        for w in keep_only_windows:
            keep |= (table["t_ns"] > (w - 1) * WINDOW_NS) & (
                table["t_ns"] <= w * WINDOW_NS
            )
        filtered = table[keep]
    else:
        filtered = table
    raw = build_clip_windows(
        filtered,
        entity_ids=pre.entity_ids,
        entity_of_host=pre.entity_of_host,
        internal_hosts=pre.internal_hosts,
        cutoff_ns=cutoff_window * WINDOW_NS,
        history_windows=HISTORY_WINDOWS,
        sensor_gap_hosts=pre.sensor_gaps,
    )
    return collate_windows(raw, scaler)


def explain_target(
    engine: ForecastEngine,
    episode: Episode,
    pre: EpisodePrecomputed,
    scaler: FeatureScaler,
    *,
    cutoff_window: int,
    entity: str,
    task_index: int,
    horizon_bins: int = 10,
    budget: AttributionBudget | None = None,
    device=None,
) -> ExplanationResult:
    """Explain one selected (entity, task, horizon) forecast output (K.1).

    The explanation replays the same prefix and the same selected output —
    never a later live state (Section 26).
    """
    budget = budget or AttributionBudget()
    n = all_pair_candidates(len(pre.entity_ids))
    request = ForecastRequest(
        horizon_bins=horizon_bins,
        bin_seconds=30,
        task_mask=torch.ones(5, dtype=torch.bool),
        min_occurrence_probability=0.30,
        published_horizons_seconds=(horizon_bins * 30,),
        candidate_pairs=n,
    )

    # Baseline on the unmodified legal prefix.
    baseline_windows = collate_windows(
        pre.prefix_windows[cutoff_window], scaler
    )
    baseline = _risk_of(
        engine, request, baseline_windows, entity, pre.entity_ids, task_index
    )

    # The entity's host index in the capture table.
    host_index = None
    for idx, host in enumerate(episode.capture.hosts):
        if host.name == entity:
            host_index = idx
            break
    if host_index is None:
        raise ValueError(f"entity {entity!r} is not an internal host")

    # Grouped deletion over the prefix windows (oldest..cutoff-1).
    window_indices = list(
        range(cutoff_window - HISTORY_WINDOWS, cutoff_window)
    )
    evidence: list[EvidenceItem] = []
    partial = False
    for w in window_indices:
        if len(evidence) >= budget.max_groups:
            partial = True
            break
        start_ns = (w - 1) * WINDOW_NS
        end_ns = w * WINDOW_NS
        table = episode.capture.packets
        rows = np.where(
            ((table["t_ns"] > start_ns) & (table["t_ns"] <= end_ns))
            & ((table["src"] == host_index) | (table["dst"] == host_index))
        )[0]
        if len(rows) == 0:
            continue
        perturbed = _build_perturbed(
            episode, pre, scaler, cutoff_window,
            delete_host=host_index, delete_window=w,
        )
        risk = _risk_of(
            engine, request, perturbed, entity, pre.entity_ids, task_index
        )
        evidence.append(
            EvidenceItem(
                category="deletion_delta",
                entity=entity,
                window_index=w,
                delta=baseline - risk,  # positive => group supported the risk
                packet_rows=tuple(int(r) for r in rows),
            )
        )

    # Rank positive-support and suppressive evidence separately (K.1).
    support = sorted(
        [e for e in evidence if e.delta > 0], key=lambda e: -e.delta
    )
    suppressive = sorted(
        [e for e in evidence if e.delta <= 0], key=lambda e: e.delta
    )
    selected = support[: budget.top_k_evidence]

    comprehensiveness = None
    sufficiency = None
    random_comp = None
    table = episode.capture.packets
    involves_all = (table["src"] == host_index) | (table["dst"] == host_index)
    if selected:
        # Comprehensiveness: remove ALL selected evidence at once (K.1).
        sel_windows = {e.window_index for e in selected}
        keep = np.ones(len(table), dtype=bool)
        for w in sel_windows:
            s, e_ = (w - 1) * WINDOW_NS, w * WINDOW_NS
            in_w = (table["t_ns"] > s) & (table["t_ns"] <= e_)
            keep &= ~(in_w & involves_all)
        raw = build_clip_windows(
            table[keep],
            entity_ids=pre.entity_ids,
            entity_of_host=pre.entity_of_host,
            internal_hosts=pre.internal_hosts,
            cutoff_ns=cutoff_window * WINDOW_NS,
            history_windows=HISTORY_WINDOWS,
            sensor_gap_hosts=pre.sensor_gaps,
        )
        risk_wo = _risk_of(
            engine, request, collate_windows(raw, scaler),
            entity, pre.entity_ids, task_index,
        )
        comprehensiveness = baseline - risk_wo

        # Sufficiency: keep ONLY the selected windows' entity traffic (all
        # other traffic of this entity is removed).
        in_sel = np.zeros(len(table), dtype=bool)
        for w in sel_windows:
            in_sel |= (table["t_ns"] > (w - 1) * WINDOW_NS) & (
                table["t_ns"] <= w * WINDOW_NS
            )
        keep_final = ~involves_all | (involves_all & in_sel)
        raw = build_clip_windows(
            table[keep_final],
            entity_ids=pre.entity_ids,
            entity_of_host=pre.entity_of_host,
            internal_hosts=pre.internal_hosts,
            cutoff_ns=cutoff_window * WINDOW_NS,
            history_windows=HISTORY_WINDOWS,
            sensor_gap_hosts=pre.sensor_gaps,
        )
        risk_only = _risk_of(
            engine, request, collate_windows(raw, scaler),
            entity, pre.entity_ids, task_index,
        )
        sufficiency = risk_only - baseline

        # Matched-size random controls.
        rng = np.random.default_rng(cutoff_window * 31 + task_index)
        non_selected = [w for w in window_indices if w not in sel_windows]
        controls = []
        for _ in range(budget.random_controls):
            if len(non_selected) < len(sel_windows):
                break
            choice = rng.choice(non_selected, size=len(sel_windows), replace=False)
            keep = np.ones(len(table), dtype=bool)
            for w in choice:
                s, e_ = (w - 1) * WINDOW_NS, w * WINDOW_NS
                in_w = (table["t_ns"] > s) & (table["t_ns"] <= e_)
                keep &= ~(in_w & involves_all)
            raw = build_clip_windows(
                table[keep],
                entity_ids=pre.entity_ids,
                entity_of_host=pre.entity_of_host,
                internal_hosts=pre.internal_hosts,
                cutoff_ns=cutoff_window * WINDOW_NS,
                history_windows=HISTORY_WINDOWS,
                sensor_gap_hosts=pre.sensor_gaps,
            )
            controls.append(
                _risk_of(
                    engine, request, collate_windows(raw, scaler),
                    entity, pre.entity_ids, task_index,
                )
            )
        if controls:
            random_comp = baseline - float(np.mean(controls))

    return ExplanationResult(
        entity=entity,
        task_index=task_index,
        horizon_bins=horizon_bins,
        baseline_risk=baseline,
        evidence=support + suppressive,
        comprehensiveness=comprehensiveness,
        sufficiency=sufficiency,
        random_baseline_comprehensiveness=random_comp,
        partial=partial,
    )
