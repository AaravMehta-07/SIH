"""Frozen novelty reference over benign episodes (Build Spec J.1).

The encoder and transition are frozen before reference fitting (A11). The
reference stores, per feature group, robust (median/MAD) statistics of
*matured residuals* — predicted observables from earlier cutoffs versus the
observations that later arrived — plus a regularized diagonal
embedding-distance reference. A robust diagonal reference is the sanctioned
starting implementation (J.1).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import torch

from ..models.types import CandidatePairs, GraphWindowBatch


def window_to_device(window: GraphWindowBatch, device) -> GraphWindowBatch:
    return GraphWindowBatch(
        x=window.x.to(device),
        edge_index=window.edge_index.to(device),
        edge_attr=window.edge_attr.to(device),
        batch=window.batch.to(device),
        slot_index=window.slot_index.to(device),
        node_present=window.node_present.to(device),
        node_observation_valid=window.node_observation_valid.to(device),
        global_raw=window.global_raw.to(device),
    )

# Node-feature groups (positions into the 44 registry). Residual aggregation
# and reporting happen per group so analysts see *which* traffic family is
# unexpected (Section 17: expose the contributing groups).
FEATURE_GROUPS: dict[str, tuple[int, ...]] = {
    "tcp_flags": (0, 1, 2, 3, 4, 5, 6, 7, 8),
    "destinations": (9, 10, 11, 12, 43),
    "graph_structure": (13, 14, 15),
    "volume": (16, 17, 18, 19, 20, 21, 22, 23, 24),
    "timing": (25, 26, 27, 28, 29, 30, 31),
    "headers": (32, 33, 34, 35),
    "loss": (36, 37),
    "payload_shape": (38, 39, 40, 41, 42),
}


@dataclass
class NoveltyReference:
    """Frozen benign reference (J.1). Fitted once; immutable afterwards."""

    group_residual_median: dict[str, np.ndarray]   # [G_positions]
    group_residual_mad: dict[str, np.ndarray]
    embedding_mean: np.ndarray                     # [64]
    embedding_scale: np.ndarray                    # [64] (diagonal reference)
    benign_false_novelty_budget: float = 0.05
    residual_threshold: float = 3.0                # standardized units
    embedding_threshold: float = 3.0
    fit_episode_count: int = 0
    fit_residual_count: int = 0

    def to_npz(self, path) -> None:
        payload = {
            "embedding_mean": self.embedding_mean,
            "embedding_scale": self.embedding_scale,
            "fit_episode_count": self.fit_episode_count,
            "fit_residual_count": self.fit_residual_count,
            "residual_threshold": self.residual_threshold,
            "embedding_threshold": self.embedding_threshold,
        }
        for group in FEATURE_GROUPS:
            payload[f"res_median::{group}"] = self.group_residual_median[group]
            payload[f"res_mad::{group}"] = self.group_residual_mad[group]
        np.savez(path, **payload)

    @classmethod
    def from_npz(cls, path) -> "NoveltyReference":
        data = np.load(path)
        ref = cls(
            group_residual_median={
                g: data[f"res_median::{g}"] for g in FEATURE_GROUPS
            },
            group_residual_mad={
                g: data[f"res_mad::{g}"] for g in FEATURE_GROUPS
            },
            embedding_mean=data["embedding_mean"],
            embedding_scale=data["embedding_scale"],
            fit_episode_count=int(data["fit_episode_count"]),
            fit_residual_count=int(data["fit_residual_count"]),
            residual_threshold=float(data["residual_threshold"]),
            embedding_threshold=float(data["embedding_threshold"]),
        )
        return ref


def _mad_scale(values: np.ndarray) -> np.ndarray:
    """Median absolute deviation, zero replaced by one (robust scaling)."""
    mad = np.median(np.abs(values - np.median(values, axis=0)), axis=0)
    return np.where(mad > 0, mad, 1.0)


def fit_novelty_reference(
    model,
    device,
    benign_examples: list,
    *,
    residual_horizon: int = 5,
    cutoff_stride: int = 5,
) -> NoveltyReference:
    """Fit the reference on benign clips (J.1).

    For each benign clip, forecasts are issued at cutoffs *inside* the clip
    (window 20..len-residual_horizon) and their predicted observables are
    compared with the actual windows that have since arrived — matured
    residuals only (NO01). Entity memories from the observed states feed the
    embedding reference.
    """
    model.eval()
    group_residuals: dict[str, list[np.ndarray]] = {
        g: [] for g in FEATURE_GROUPS
    }
    embeddings: list[np.ndarray] = []
    residual_count = 0
    episode_ids = {ex.episode_id for ex in benign_examples}

    with torch.no_grad():
        for ex in benign_examples:
            num_windows = len(ex.windows)
            # Replay forecasts at cutoffs INSIDE the 20-window clip; each
            # prediction is compared with the clip's actual windows that
            # arrive after that cutoff (matured by construction, NO01).
            for cutoff in range(5, num_windows - residual_horizon + 1, cutoff_stride):
                past = [window_to_device(w, device) for w in ex.windows[:cutoff]]
                observed = model.observe_clip(past)
                outputs = model.roll_out(observed, residual_horizon)
                # predicted node features per future bin [H, N, 44]
                predicted = torch.stack(
                    [o.node_mean[0] for o in outputs], dim=0
                ).cpu().numpy()
                for h in range(residual_horizon):
                    window = ex.windows[cutoff + h]
                    actual = window.x[0, :44].cpu().numpy()
                    validity = window.x[0, 44:].cpu().numpy()
                    residual = (actual - predicted[h]) * validity
                    for group, positions in FEATURE_GROUPS.items():
                        pos = list(positions)
                        group_residuals[group].append(
                            residual[:, pos].reshape(-1, len(pos))
                        )
                    residual_count += int(validity.sum())
            state = model.observe_clip([window_to_device(w, device) for w in ex.windows])
            embeddings.append(state.entity_memory[0].cpu().numpy())

    group_median = {}
    group_mad = {}
    for group, chunks in group_residuals.items():
        stacked = np.concatenate(chunks, axis=0)
        group_median[group] = np.median(stacked, axis=0)
        group_mad[group] = _mad_scale(stacked)

    emb = np.concatenate(embeddings, axis=0)  # [K, 64]
    emb_mean = emb.mean(axis=0)
    emb_scale = np.where(emb.std(axis=0) > 0, emb.std(axis=0), 1.0)

    return NoveltyReference(
        group_residual_median=group_median,
        group_residual_mad=group_mad,
        embedding_mean=emb_mean,
        embedding_scale=emb_scale,
        fit_episode_count=len(episode_ids),
        fit_residual_count=residual_count,
    )
