"""Manifests, split construction and clip loading (Build Spec M.1, G.4)."""

from .clips import (
    ClipDataset,
    ClipExample,
    sample_cutoffs,
)
from .episodes import (
    CAMPAIGNS,
    CORPUS_PLAN,
    EPISODE_WINDOWS,
    Episode,
    StageWindow,
    build_corpus,
    build_episode,
)
from .splits import Splits, split_episodes

__all__ = [
    "ClipDataset",
    "ClipExample",
    "sample_cutoffs",
    "CAMPAIGNS",
    "CORPUS_PLAN",
    "EPISODE_WINDOWS",
    "Episode",
    "StageWindow",
    "build_corpus",
    "build_episode",
    "Splits",
    "split_episodes",
]
