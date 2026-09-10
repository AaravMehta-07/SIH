"""Clip dataset construction (Build Spec G.4, Section 15).

A clip is one decision cutoff on the 30-second grid: 20 eligible history
windows (prefix) plus the training-only future targets (labels module; the
serving path never instantiates the target object — Appendix C.2).

Cutoffs are sampled every second grid window from the 20th to the
(EPISODE_WINDOWS - 60)th window, so pre-event, imminent-event and
post-event phases are all covered. Overlapping cutoffs are training
exposure, never independent evaluation units (G.4); the evaluator counts
alerts with cooldown and bootstraps at episode level (M.3/M.4).
"""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ..features.transforms import FeatureScaler, fit_scaler
from ..features.windows import RawGraphWindow, build_clip_windows
from ..graphs.collate import collate_windows
from ..ingest.synthetic import PROTO_TCP
from ..labels.targets import build_clip_targets
from ..models.types import GraphWindowBatch
from ..training.targets import ClipTargets
from .episodes import EPISODE_WINDOWS, Episode

_NS = 1_000_000_000
WINDOW_NS = 30 * _NS
HISTORY_WINDOWS = 20
HORIZON_BINS = 60

#: Cutoff grid: every fourth window from 20 to 80 (16 per episode). The
#: stride is a memory/compute budget choice — highly overlapping cutoffs
#: are training exposure, never independent units (G.4); stride 4 keeps
#: non-overlapping primary horizons and complete event-phase coverage.
CUTOFF_STEP = 4


def sample_cutoffs(episode: Episode, *, horizon: int = HORIZON_BINS) -> list[int]:
    """Grid window indices (1-based window count) usable as cutoffs.

    Cutoffs run from the first full-history window (20) to window 80: every
    cutoff has complete primary-horizon (10-bin) follow-up to the episode
    end; cutoffs beyond window 50 carry censored 60-bin targets (incomplete
    later bins contribute no negatives, Section 15). This covers pre-campaign,
    imminent-event and post-onset phases for every task.
    """
    last = 80
    return list(range(HISTORY_WINDOWS, last + 1, CUTOFF_STEP))


@dataclass
class EpisodePrecomputed:
    """Raw windows and target inputs for every cutoff of one episode."""

    episode_id: str
    entity_ids: tuple[str, ...]
    entity_of_host: dict[int, int]
    internal_hosts: set[int]
    sensor_gaps: dict[int, list[tuple[int, int]]]
    full_windows: list[RawGraphWindow]          # 110 full-info windows
    prefix_windows: dict[int, list[RawGraphWindow]]  # cutoff window -> 20 raw


def precompute_episode(episode: Episode) -> EpisodePrecomputed:
    """Build all raw windows (full-info + per-cutoff prefixes) once."""
    capture = episode.capture
    entity_ids = episode.internal_entity_ids()
    n = len(entity_ids)
    slot_of = {name: i for i, name in enumerate(entity_ids)}

    entity_of_host: dict[int, int] = {}
    internal_hosts: set[int] = set()
    next_external = n
    for idx, host in enumerate(capture.hosts):
        if host.name in slot_of:
            entity_of_host[idx] = slot_of[host.name]
            internal_hosts.add(idx)
        else:
            entity_of_host[idx] = next_external
            next_external += 1

    sensor_gaps: dict[int, list[tuple[int, int]]] = {}
    for name, f, t in capture.sensor_gaps:
        for idx, host in enumerate(capture.hosts):
            if host.name == name:
                sensor_gaps.setdefault(idx, []).append((f, t))

    table = capture.packets

    # Full-information windows (label side; may see everything). The grid is
    # anchored at episode start: window i covers (i*30s, (i+1)*30s], so the
    # full set is exactly the 110 windows ending at the episode end.
    full = build_clip_windows(
        table,
        entity_ids=entity_ids,
        entity_of_host=entity_of_host,
        internal_hosts=internal_hosts,
        cutoff_ns=EPISODE_WINDOWS * WINDOW_NS,
        history_windows=EPISODE_WINDOWS,
        sensor_gap_hosts=sensor_gaps,
    )

    prefix: dict[int, list[RawGraphWindow]] = {}
    for cutoff_window in sample_cutoffs(episode):
        cutoff_ns = cutoff_window * WINDOW_NS
        prefix[cutoff_window] = build_clip_windows(
            table,
            entity_ids=entity_ids,
            entity_of_host=entity_of_host,
            internal_hosts=internal_hosts,
            cutoff_ns=cutoff_ns,
            history_windows=HISTORY_WINDOWS,
            sensor_gap_hosts=sensor_gaps,
        )
    return EpisodePrecomputed(
        episode_id=episode.episode_id,
        entity_ids=entity_ids,
        entity_of_host=entity_of_host,
        internal_hosts=internal_hosts,
        sensor_gaps=sensor_gaps,
        full_windows=full,
        prefix_windows=prefix,
    )


def build_serving_windows(
    pre: EpisodePrecomputed, scaler: FeatureScaler, cutoff_window: int
) -> tuple[list, "CandidatePairs"]:
    """Serving path (G.4): scaled prefix windows + the frozen candidate set,
    WITHOUT the training target object — the serving loader never
    instantiates ClipTargets (Appendix C.2)."""
    from ..labels.targets import all_pair_candidates

    windows = collate_windows(pre.prefix_windows[cutoff_window], scaler)
    candidates = all_pair_candidates(len(pre.entity_ids))
    return windows, candidates


@dataclass
class ClipExample:
    """One training/evaluation clip: scaled model windows + D.6 targets."""

    episode_id: str
    family: str
    split: str
    cutoff_window: int
    cutoff_ns: int
    entity_ids: tuple[str, ...]
    windows: list[GraphWindowBatch]
    targets: ClipTargets


def build_clip_example(
    episode: Episode,
    pre: EpisodePrecomputed,
    cutoff_window: int,
    scaler: FeatureScaler,
    *,
    split: str,
    horizon: int = HORIZON_BINS,
) -> ClipExample:
    """Scale the prefix windows and attach the D.6 targets."""
    cutoff_ns = cutoff_window * WINDOW_NS
    windows = collate_windows(pre.prefix_windows[cutoff_window], scaler)

    # Future observable targets: full-info windows after the cutoff.
    future = pre.full_windows[cutoff_window : cutoff_window + horizon]
    stages = [
        (s.entity, s.tactic_index, s.from_ns, s.to_ns) for s in episode.stages
    ]
    targets = build_clip_targets(
        entity_ids=pre.entity_ids,
        ground_truth=episode.ground_truth,
        stage_windows=stages,
        cutoff_ns=cutoff_ns,
        horizon=horizon,
        future_windows=future,
        scaler=scaler,
        split=split,
        followup_end_ns=episode.end_ns,
    )
    return ClipExample(
        episode_id=episode.episode_id,
        family=episode.family,
        split=split,
        cutoff_window=cutoff_window,
        cutoff_ns=cutoff_ns,
        entity_ids=pre.entity_ids,
        windows=windows,
        targets=targets,
    )


class ClipDataset:
    """Lazily-built, disk-cached clip collection over a split's episodes."""

    def __init__(
        self,
        episodes: list[Episode],
        *,
        split: str,
        scaler: FeatureScaler,
        cache_dir: Path | None = None,
        horizon: int = HORIZON_BINS,
    ) -> None:
        self.episodes = episodes
        self.split = split
        self.scaler = scaler
        self.cache_dir = cache_dir
        self.horizon = horizon
        self._examples: list[ClipExample] | None = None

    def _cache_path(self, episode: Episode) -> Path | None:
        if self.cache_dir is None:
            return None
        digest = hashlib.sha256(
            f"{episode.episode_id}:{episode.seed}:{self.split}:{self.horizon}".encode()
        ).hexdigest()[:16]
        return self.cache_dir / f"{episode.episode_id}-{digest}.pkl"

    def _load_or_build(self, episode: Episode) -> list[ClipExample]:
        cache = self._cache_path(episode)
        wanted = set(sample_cutoffs(episode, horizon=self.horizon))
        if cache is not None and cache.exists():
            with open(cache, "rb") as handle:
                # Older cache entries may carry a denser cutoff grid; the
                # active stride governs what the dataset exposes (G.4).
                return [
                    ex
                    for ex in pickle.load(handle)
                    if ex.cutoff_window in wanted
                ]
        pre = precompute_episode(episode)
        examples = [
            build_clip_example(
                episode, pre, cutoff, self.scaler,
                split=self.split, horizon=self.horizon,
            )
            for cutoff in sample_cutoffs(episode, horizon=self.horizon)
        ]
        if cache is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with open(cache, "wb") as handle:
                pickle.dump(examples, handle, protocol=pickle.HIGHEST_PROTOCOL)
        return examples

    def examples(self) -> list[ClipExample]:
        if self._examples is None:
            all_examples: list[ClipExample] = []
            for episode in self.episodes:
                all_examples.extend(self._load_or_build(episode))
            self._examples = all_examples
        return self._examples

    def fit_scaler_from_train(self) -> FeatureScaler:
        """Fit the F.8 scaler on this dataset's raw prefix windows (train
        split only; never per uploaded file)."""
        windows: list[RawGraphWindow] = []
        for episode in self.episodes:
            pre = precompute_episode(episode)
            for cutoff in sample_cutoffs(episode, horizon=self.horizon):
                windows.extend(pre.prefix_windows[cutoff])
        return fit_scaler(windows)


def episode_asset_table(episode: Episode) -> dict:
    """Per-episode observation support for asset-hour accounting (M.4):
    observed internal host count and observed window span."""
    capture = episode.capture
    table = capture.packets
    internal = [
        i for i, h in enumerate(capture.hosts)
        if h.name.endswith((".corp.local", ".dmz.local"))
    ]
    observed = {
        capture.hosts[i].name
        for i in internal
        if ((table["src"] == i) | (table["dst"] == i)).any()
    }
    return {
        "episode_id": episode.episode_id,
        "internal_hosts": len(internal),
        "observed_hosts": len(observed),
        "observed_host_names": sorted(observed),
        "windows": EPISODE_WINDOWS,
        "observed_asset_hours": len(observed) * EPISODE_WINDOWS * 30 / 3600.0,
    }
