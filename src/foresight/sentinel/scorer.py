"""Sentinel scoring over matured residuals and embeddings (J.1, J.3).

The scorer never maps novelty to attack probability (A09) and never uses a
future residual of the current forecast (NO01): ``MaturedResidual`` inputs
are produced only by ``collect_matured_residuals``, which requires the
observed window to have arrived after the forecast that predicted it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch

from .reference import FEATURE_GROUPS, NoveltyReference, window_to_device

NOVELTY_REFERENCE_LIKE = "reference_like"
NOVELTY_NOVEL = "novel"
NOVELTY_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class MaturedResidual:
    """One matured prediction-versus-arrival residual (NO01-safe).

    ``forecast_cutoff_window < observed_window`` is enforced at construction:
    the observation must have arrived strictly after the forecast cutoff.
    """

    entity: str
    forecast_cutoff_window: int
    observed_window: int
    residuals: np.ndarray  # [44] transformed-space (predicted - actual)

    def __post_init__(self) -> None:
        if self.observed_window <= self.forecast_cutoff_window:
            raise ValueError(
                "NO01: only matured residuals (observed after forecast) are "
                "legal sentinel inputs"
            )


def collect_matured_residuals(
    model,
    device,
    clip_windows,
    *,
    entity_ids: tuple[str, ...],
    latest_cutoff_window: int,
    residual_horizon: int = 5,
) -> list[MaturedResidual]:
    """Matured residuals available at ``latest_cutoff_window`` (J.1).

    Forecasts are replayed at earlier cutoffs of the same clip; each
    prediction for window w is paired with the observation at w, which has
    arrived because w <= latest_cutoff_window. Residual novelty is
    unavailable during warmup (fewer than ``residual_horizon`` matured
    windows): return an empty list and the scorer reports ``unavailable``.
    """
    num_windows = len(clip_windows)
    out: list[MaturedResidual] = []
    if num_windows <= 20 + residual_horizon:
        return out  # warmup: nothing matured yet
    model.eval()
    with torch.no_grad():
        # Forecasts replayed at cutoffs INSIDE the clip; each prediction is
        # paired with the clip's actual window that arrives after it
        # (matured by construction, NO01).
        for cutoff in range(5, num_windows - residual_horizon + 1, 5):
            past = [window_to_device(w, device) for w in clip_windows[:cutoff]]
            observed = model.observe_clip(past)
            outputs = model.roll_out(observed, residual_horizon)
            predicted = (
                torch.stack([o.node_mean[0] for o in outputs], dim=0).cpu().numpy()
            )  # [H, N, 44]
            for h in range(residual_horizon):
                observed_window_idx = cutoff + h  # 0-indexed window array
                if observed_window_idx >= num_windows:
                    break
                actual = clip_windows[observed_window_idx].x[0, :44].cpu().numpy()
                validity = clip_windows[observed_window_idx].x[0, 44:].cpu().numpy()
                residual = (actual - predicted[h]) * validity
                for slot, entity in enumerate(entity_ids):
                    out.append(
                        MaturedResidual(
                            entity=entity,
                            forecast_cutoff_window=cutoff,
                            observed_window=observed_window_idx + 1,
                            residuals=residual[slot].astype(np.float64),
                        )
                    )
    return out


@dataclass
class NoveltyDiagnostics:
    """Section-18 novelty axis output with per-group contributions."""

    status: str
    residual_score: float | None
    embedding_distance: float | None
    contributing_groups: list[str] = field(default_factory=list)
    per_group: dict[str, float] = field(default_factory=dict)
    note: str = ""

    def to_json(self) -> dict:
        return {
            "status": self.status,
            "residual_score": self.residual_score,
            "embedding_distance": self.embedding_distance,
            "contributing_groups": self.contributing_groups,
            "per_group": self.per_group,
            "note": self.note,
        }


class SentinelScorer:
    """Score matured residuals and embeddings against the frozen reference.

    Novelty is unexpectedness relative to the reference. A benign change
    (patch rollout, new service) is change detection only — the note says so
    and nothing here converts the score to attack probability (A09).
    """

    def __init__(self, reference: NoveltyReference) -> None:
        self.reference = reference

    def score(
        self,
        entity_memory: torch.Tensor | None,
        matured: list[MaturedResidual],
        entity: str | None = None,
    ) -> NoveltyDiagnostics:
        ref = self.reference

        # Embedding distance (correlated evidence — same encoder, Section 17)
        emb_distance: float | None = None
        if entity_memory is not None and entity_memory.numel() > 0:
            emb = entity_memory.detach().cpu().numpy().astype(np.float64)
            z = np.abs(emb - ref.embedding_mean) / ref.embedding_scale
            emb_distance = float(np.linalg.norm(z) / np.sqrt(len(z)))

        if not matured:
            return NoveltyDiagnostics(
                status=NOVELTY_UNAVAILABLE,
                residual_score=None,
                embedding_distance=emb_distance,
                note=(
                    "residual novelty unavailable (warmup: no matured "
                    "residuals at this cutoff); embedding distance is "
                    "correlated evidence from the same encoder, not an "
                    "independent sensor"
                ),
            )

        per_group: dict[str, float] = {}
        entity_residuals = [m for m in matured if entity is None or m.entity == entity]
        if not entity_residuals:
            return NoveltyDiagnostics(
                status=NOVELTY_UNAVAILABLE,
                residual_score=None,
                embedding_distance=emb_distance,
                note="no matured residuals for this entity",
            )
        stacked = np.stack([m.residuals for m in entity_residuals], axis=0)
        for group, positions in FEATURE_GROUPS.items():
            pos = list(positions)
            g = stacked[:, pos]
            z = np.abs(g - ref.group_residual_median[group]) / ref.group_residual_mad[group]
            per_group[group] = float(np.median(z.max(axis=1)))

        residual_score = max(per_group.values())
        novel = residual_score > ref.residual_threshold or (
            emb_distance is not None and emb_distance > ref.embedding_threshold
        )
        contributing = [
            g for g, s in per_group.items() if s > ref.residual_threshold
        ]
        return NoveltyDiagnostics(
            status=NOVELTY_NOVEL if novel else NOVELTY_REFERENCE_LIKE,
            residual_score=residual_score,
            embedding_distance=emb_distance,
            contributing_groups=contributing,
            per_group=per_group,
            note=(
                "unexpectedness relative to the frozen benign reference; "
                "benign change (rollouts, new services) also triggers this — "
                "not an attack probability"
            ),
        )
