"""Feature transforms and the fitted scaler artifact (Build Spec F.8).

One transform per value column from the registry (no runtime inference):
``log1p`` for nonnegative unbounded quantities, identity for bounded ones.
Median/IQR robust scaling is fitted on valid **training** values only; zero
IQR becomes one; an entirely unobserved training field stays unsupported and
masked at serve time. The complete transform vector is stored in the model
bundle (Section 10).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from .registry import EDGE_FEATURE_NAMES, GLOBAL_FEATURE_NAMES, NODE_FEATURE_NAMES, TRANSFORMS
from .windows import RawGraphWindow


@dataclass(frozen=True)
class FeatureScaler:
    """Fitted median/IQR transform for the 44/11/24 registry (F.8)."""

    node_median: np.ndarray        # float64 [44] in raw space
    node_iqr: np.ndarray           # float64 [44], zero replaced by one
    node_supported: np.ndarray     # bool [44]
    edge_median: np.ndarray        # [11]
    edge_iqr: np.ndarray
    edge_supported: np.ndarray
    global_median: np.ndarray      # [24]
    global_iqr: np.ndarray
    global_supported: np.ndarray
    training_split_hash: str = ""

    def transform_values(
        self, values: np.ndarray, validity: np.ndarray, kind: str
    ) -> tuple[np.ndarray, np.ndarray]:
        """Apply per-column transforms (log1p or identity, F.8) then robust
        median/IQR scaling to valid entries.

        Invalid entries become exact zero with mask zero (F.8). Values far
        beyond the training range are NOT clipped — they are drift evidence.
        """
        med, iqr, supported, transforms = self._params(kind)
        log_mask = np.array([t == "log1p" for t in transforms])
        out = np.zeros_like(values, dtype=np.float64)
        valid = validity & supported
        if values.ndim == 1:
            out[log_mask] = np.log1p(values[log_mask])
            out[~log_mask] = values[~log_mask]
            out[~valid] = 0.0
            safe_iqr = np.where(iqr > 0, iqr, 1.0)
            out = (out - med) / safe_iqr
            out[~valid] = 0.0
            return out.astype(np.float32), valid
        # [N, F] layout
        out[:, log_mask] = np.log1p(values[:, log_mask])
        out[:, ~log_mask] = values[:, ~log_mask]
        out[~valid] = 0.0
        safe_iqr = np.where(iqr > 0, iqr, 1.0)
        out = (out - med) / safe_iqr
        out[~valid] = 0.0
        return out.astype(np.float32), valid

    def _params(self, kind: str):
        return {
            "node": (
                self.node_median,
                self.node_iqr,
                self.node_supported,
                TRANSFORMS["node"],
            ),
            "edge": (
                self.edge_median,
                self.edge_iqr,
                self.edge_supported,
                TRANSFORMS["edge"],
            ),
            "global": (
                self.global_median,
                self.global_iqr,
                self.global_supported,
                TRANSFORMS["global"],
            ),
        }[kind]

    def to_json(self) -> dict:
        return {
            "schema": "foresight.core.2026-09",
            "node_feature_names": list(NODE_FEATURE_NAMES),
            "edge_feature_names": list(EDGE_FEATURE_NAMES),
            "global_feature_names": list(GLOBAL_FEATURE_NAMES),
            "node_median": self.node_median.tolist(),
            "node_iqr": self.node_iqr.tolist(),
            "node_supported": self.node_supported.tolist(),
            "edge_median": self.edge_median.tolist(),
            "edge_iqr": self.edge_iqr.tolist(),
            "edge_supported": self.edge_supported.tolist(),
            "global_median": self.global_median.tolist(),
            "global_iqr": self.global_iqr.tolist(),
            "global_supported": self.global_supported.tolist(),
            "training_split_hash": self.training_split_hash,
        }

    @classmethod
    def from_json(cls, payload: dict) -> "FeatureScaler":
        return cls(
            node_median=np.array(payload["node_median"], dtype=np.float64),
            node_iqr=np.array(payload["node_iqr"], dtype=np.float64),
            node_supported=np.array(payload["node_supported"], dtype=bool),
            edge_median=np.array(payload["edge_median"], dtype=np.float64),
            edge_iqr=np.array(payload["edge_iqr"], dtype=np.float64),
            edge_supported=np.array(payload["edge_supported"], dtype=bool),
            global_median=np.array(payload["global_median"], dtype=np.float64),
            global_iqr=np.array(payload["global_iqr"], dtype=np.float64),
            global_supported=np.array(payload["global_supported"], dtype=bool),
            training_split_hash=payload.get("training_split_hash", ""),
        )

    def serialize(self) -> str:
        return json.dumps(self.to_json(), sort_keys=True)


def fit_scaler(
    windows: list[RawGraphWindow], *, training_split_hash: str = ""
) -> FeatureScaler:
    """Fit medians and IQRs on valid training values only (F.8).

    Fit happens once per training corpus — never per uploaded file. An
    entirely unobserved field is unsupported (masked at serve).
    """

    def fit(values_list: list[np.ndarray], valid_list: list[np.ndarray], n: int):
        medians = np.zeros(n)
        iqrs = np.ones(n)
        supported = np.zeros(n, dtype=bool)
        if not values_list:
            return medians, iqrs, supported
        stacked_v = np.concatenate([v.reshape(-1, n) for v in values_list], axis=0)
        stacked_m = np.concatenate([m.reshape(-1, n) for m in valid_list], axis=0)
        for f in range(n):
            column = stacked_v[stacked_m[:, f], f]
            if len(column) == 0:
                continue  # unsupported field stays masked (F.8)
            supported[f] = True
            medians[f] = float(np.median(column))
            q75, q25 = np.percentile(column, [75, 25])
            iqr = float(q75 - q25)
            iqrs[f] = iqr if iqr > 0 else 1.0  # zero IQR replaced by one (F.8)
        return medians, iqrs, supported

    node_m, node_i, node_s = fit(
        [w.node_values for w in windows],
        [w.node_validity for w in windows],
        44,
    )
    edge_m, edge_i, edge_s = fit(
        [w.edge_values for w in windows if len(w.edge_values)],
        [w.edge_validity for w in windows if len(w.edge_values)],
        11,
    )
    glob_m, glob_i, glob_s = fit(
        [w.global_values.reshape(1, 24) for w in windows],
        [w.global_validity.reshape(1, 24) for w in windows],
        24,
    )
    return FeatureScaler(
        node_median=node_m,
        node_iqr=node_i,
        node_supported=node_s,
        edge_median=edge_m,
        edge_iqr=edge_i,
        edge_supported=edge_s,
        global_median=glob_m,
        global_iqr=glob_i,
        global_supported=glob_s,
        training_split_hash=training_split_hash,
    )


def transform_window(
    window: RawGraphWindow, scaler: FeatureScaler
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Scale one raw window: values-then-validity layouts (D.5).

    Returns ``(node_x [N,88], edge_x [E,22], global_x [48])`` pieces:
    ``node_x`` concatenates 44 scaled values then 44 validity bits (not
    interleaved), same for edges (22) and globals (48).
    """
    node_scaled, node_valid = scaler.transform_values(
        window.node_values, window.node_validity, "node"
    )
    if len(window.edge_values):
        edge_scaled, edge_valid = scaler.transform_values(
            window.edge_values, window.edge_validity, "edge"
        )
    else:
        edge_scaled = np.zeros((0, 11), dtype=np.float32)
        edge_valid = np.zeros((0, 11), dtype=bool)
    global_scaled, global_valid = scaler.transform_values(
        window.global_values, window.global_validity, "global"
    )

    node_x = np.concatenate(
        [node_scaled, node_valid.astype(np.float32)], axis=1
    ).astype(np.float32)
    edge_x = (
        np.concatenate(
            [edge_scaled, edge_valid.astype(np.float32)], axis=1
        ).astype(np.float32)
        if len(edge_scaled)
        else np.zeros((0, 22), dtype=np.float32)
    )
    global_x = np.concatenate(
        [global_scaled, global_valid.astype(np.float32)]
    ).astype(np.float32)
    return node_x, edge_x, global_x, node_valid, edge_valid, global_valid


__all__ = [
    "FeatureScaler",
    "fit_scaler",
    "transform_window",
    "TRANSFORMS",
]
