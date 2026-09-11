"""Tier B attack-path engine (Build Spec Section 20, Appendix N.2).

The next-mark decoder conditions on the observed world state and previously
generated marks; a mark is ``(event_type, source, target, time_bin)`` with an
allowed-type mask. Teacher forcing predicts the next observed mark in
training; free generation feeds predicted marks back through beam search
(width 8, depth 4) with explicit truncated mass.

Honesty contract (Section 20 / A18):

- Path scores are autoregressive products over the next-mark distribution —
  they are NEVER a calibrated attack-path probability; ``calibrated`` is
  always ``false`` and requires held-out path evaluation to change.
- The candidate set comes from observed reachable entities, authorized
  inventory, prior communications and observed external endpoints; a
  no-event option and an outside-candidate option carry their own mass.
- Candidate recall is measured before any ranker judgment (N.2).
- Independent edge marginals are never multiplied and relabeled a path
  posterior; this decoder is a separate task from the event-time hazards.
"""

from .candidates import CandidateSet, MarkOption, build_candidate_set
from .engine import PathEngine, PathForecast
from .model import NextMarkDecoder

PATH_ENGINE_SCHEMA = "foresight.paths.2026-09"

__all__ = [
    "CandidateSet",
    "MarkOption",
    "build_candidate_set",
    "PathEngine",
    "PathForecast",
    "NextMarkDecoder",
    "PATH_ENGINE_SCHEMA",
]
