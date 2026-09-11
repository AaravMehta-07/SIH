"""Serving-side path engine (Build Spec Section 20, N.3 answer contract).

Assembles a path forecast at a cutoff: observed world state (reference
member) -> candidate set from eligible-prefix telemetry -> beam search ->
typed result with explicit mass accounting. The Tier A candidate-edge
projection (marginal future-communication probabilities) remains a separate
output; the two are never merged into one "path probability".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import torch

from ..data.episodes import Episode
from .beam import beam_search
from .candidates import (
    CandidateSet,
    build_candidate_set,
    external_buckets,
)
from .model import NextMarkDecoder

PATH_BUNDLE_FILES = ("manifest.json", "model.safetensors")


class PathArtifactError(RuntimeError):
    """Path bundle missing, incomplete or hash-mismatched."""


@dataclass(frozen=True)
class PathForecast:
    """Typed path result (Section 20 reported fields)."""

    ranked_paths: list[dict]
    no_event_mass: float
    outside_candidate_mass: float
    truncated_search_mass: float
    beam_width: int
    beam_depth: int
    candidate_pairs: dict

    def to_json(self) -> dict:
        total = (
            sum(float(p.get("probability", 0.0)) for p in self.ranked_paths)
            + self.no_event_mass
            + self.outside_candidate_mass
            + self.truncated_search_mass
        )
        return {
            "status": "supported",
            "ranked_paths": self.ranked_paths,
            "no_event_mass": self.no_event_mass,
            "outside_candidate_mass": self.outside_candidate_mass,
            "truncated_search_mass": self.truncated_search_mass,
            "mass_accounting_total": round(total, 6),
            "beam": {"width": self.beam_width, "depth": self.beam_depth},
            "candidate_pairs": self.candidate_pairs,
            "calibrated": False,
            "note": (
                "Autoregressive next-mark products over the candidate "
                "universe (Section 20); ranked hypotheses, not a calibrated "
                "attack-path probability. Separate task from the event-time "
                "hazard heads."
            ),
        }


class PathEngine:
    """Trained next-mark decoder + beam search over candidate marks."""

    def __init__(
        self,
        decoder: NextMarkDecoder,
        *,
        beam_width: int = 8,
        beam_depth: int = 4,
        weights_profile: str = "",
    ) -> None:
        self.decoder = decoder
        self.beam_width = beam_width
        self.beam_depth = beam_depth
        self.weights_profile = weights_profile
        self.decoder.eval()

    @torch.no_grad()
    def forecast(
        self,
        episode: Episode,
        entity_memory: torch.Tensor,   # [1, N, 64] observed state (internal)
        global_context: torch.Tensor,  # [1, 24]
        cutoff_window: int,
        *,
        candidates: CandidateSet | None = None,
    ) -> PathForecast:
        cands = candidates or build_candidate_set(episode, cutoff_window)
        device = entity_memory.device
        pair_src = torch.tensor(
            [
                cands.node_names.index(s) if s in cands.node_names else -1
                for (s, _t) in cands.pairs
            ],
            device=device,
        )
        pair_tgt = torch.tensor(
            [
                cands.node_names.index(t) if t in cands.node_names else -1
                for (_s, t) in cands.pairs
            ],
            device=device,
        )
        ext = torch.tensor(
            external_buckets(cands.node_names, cands.internal_count),
            device=device,
        )
        result = beam_search(
            self.decoder,
            entity_memory,
            global_context,
            ext,
            pair_src,
            pair_tgt,
            cands,
            width=self.beam_width,
            depth=self.beam_depth,
        )
        payload = result.to_json()
        return PathForecast(
            ranked_paths=payload["ranked_paths"],
            no_event_mass=payload["no_event_mass"],
            outside_candidate_mass=payload["outside_candidate_mass"],
            truncated_search_mass=payload["truncated_search_mass"],
            beam_width=self.beam_width,
            beam_depth=self.beam_depth,
            candidate_pairs=cands.to_json(),
        )


def load_path_engine(root: Path) -> PathEngine | None:
    """Load the trained path bundle (artifacts/paths) with hash
    verification; None when absent (the honest not_supported state)."""
    import hashlib

    from safetensors.torch import load_file

    if not root.is_dir() or not all(
        (root / f).exists() for f in PATH_BUNDLE_FILES
    ):
        return None
    manifest = json.loads(
        (root / "manifest.json").read_text(encoding="utf-8")
    )
    hashes = manifest.get("hashes", {})
    for name, expected in hashes.items():
        path = root / name
        if not path.exists():
            raise PathArtifactError(f"path bundle file missing: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            raise PathArtifactError(f"path bundle hash mismatch: {name}")
    decoder = NextMarkDecoder()
    decoder.load_state_dict(load_file(str(root / "model.safetensors")))
    profile = manifest.get(
        "weights_profile",
        "Tier B next-mark decoder (synthetic corpus, disclosed)",
    )
    return PathEngine(
        decoder,
        beam_width=int(manifest.get("beam_width", 8)),
        beam_depth=int(manifest.get("beam_depth", 4)),
        weights_profile=profile,
    )
