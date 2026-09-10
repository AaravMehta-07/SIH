"""Chronological episode-level splits with embargo (Build Spec M.1, Section 29).

Episode/campaign-level partitions in default 60/15/10/15 proportions
(train/development/calibration/locked-test). Embargo: at least 2400 seconds
where raw records could cross boundaries; synthetic episodes are disjoint by
construction, and the embargo is recorded in the manifest regardless. A
chronological row split inside one campaign is insufficient (M.1) — the unit
is the episode.
"""

from __future__ import annotations

from dataclasses import dataclass

from .episodes import Episode

SPLIT_NAMES = ("train", "development", "calibration", "locked_test")
DEFAULT_PROPORTIONS = (0.60, 0.15, 0.10, 0.15)
EMBARGO_SECONDS = 2400

#: Deterministic family-balanced interleave so every split sees every family
#: while order stays chronological-by-construction-index (M.1 disclosure:
#: synthetic episodes have no real capture time; the corpus index is the
#: chronological proxy and is disclosed as such).
_FAMILY_ORDER = (
    "benign",
    "web-lateral",
    "benign-drift",
    "c2-exfil",
    "slow-recon",
    "cred-spray",
)


@dataclass(frozen=True)
class Splits:
    train: tuple[Episode, ...]
    development: tuple[Episode, ...]
    calibration: tuple[Episode, ...]
    locked_test: tuple[Episode, ...]
    embargo_seconds: int = EMBARGO_SECONDS
    proportions: tuple[float, float, float, float] = DEFAULT_PROPORTIONS

    def episodes_of(self, split: str) -> tuple[Episode, ...]:
        if split == "locked_test":
            return self.locked_test
        return getattr(self, split)

    def manifest(self) -> dict:
        return {
            "unit": "campaign_episode",
            "embargo_seconds": self.embargo_seconds,
            "proportions": list(self.proportions),
            "train": [e.episode_id for e in self.train],
            "development": [e.episode_id for e in self.development],
            "calibration": [e.episode_id for e in self.calibration],
            "locked_test": [e.episode_id for e in self.locked_test],
            "families": {
                split: sorted({e.family for e in self.episodes_of(split)})
                for split in SPLIT_NAMES
            },
        }


def split_episodes(
    episodes: list[Episode],
    *,
    proportions: tuple[float, float, float, float] = DEFAULT_PROPORTIONS,
) -> Splits:
    """Family-balanced chronological split at whole-episode granularity.

    Episodes are interleaved by family so each partition contains every
    family (small-corpus honesty: with ~72 episodes a plain chronological
    cut could starve a split of a family; the interleave is deterministic,
    disclosed in the manifest, and never row-level).
    """
    if abs(sum(proportions) - 1.0) > 1e-9:
        raise ValueError("split proportions must sum to 1")

    by_family: dict[str, list[Episode]] = {}
    for ep in episodes:
        by_family.setdefault(ep.family, []).append(ep)

    ordered: list[Episode] = []
    family_lists = {
        f: iter(sorted(by_family.get(f, []), key=lambda e: e.episode_id))
        for f in _FAMILY_ORDER
    }
    remaining = sum(len(v) for v in by_family.values())
    while remaining > 0:
        for f in _FAMILY_ORDER:
            nxt = next(family_lists[f], None)
            if nxt is not None:
                ordered.append(nxt)
                remaining -= 1

    n = len(ordered)
    n_train = round(n * proportions[0])
    n_dev = round(n * proportions[1])
    n_cal = round(n * proportions[2])
    return Splits(
        train=tuple(ordered[:n_train]),
        development=tuple(ordered[n_train : n_train + n_dev]),
        calibration=tuple(ordered[n_train + n_dev : n_train + n_dev + n_cal]),
        locked_test=tuple(ordered[n_train + n_dev + n_cal :]),
    )
