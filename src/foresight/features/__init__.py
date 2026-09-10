"""Prefix-safe feature engineering (Build Spec Section 10, Appendix F).

``build_window`` turns eligible packet telemetry into a raw D.5 GraphWindow:
44 node values + 44 validity bits, 11 edge values + 11 bits, 24 global values
+ 24 bits, evidence index, unscaled (F.8: scaling is a separate fitted
artifact; raw arrays stay unscaled in storage).

Window grid: 30-second UTC windows ``(start, end]``; the first packet on an
exact boundary belongs to the preceding window (F.5, TM05).
"""

from .registry import (
    EDGE_FEATURE_NAMES,
    GLOBAL_FEATURE_NAMES,
    NODE_FEATURE_NAMES,
    TRANSFORMS,
    edge_transform_of,
    global_transform_of,
    node_transform_of,
)
from .transforms import FeatureScaler, fit_scaler, transform_window
from .windows import (
    RawGraphWindow,
    build_clip_windows,
    window_bounds,
)

__all__ = [
    "EDGE_FEATURE_NAMES",
    "GLOBAL_FEATURE_NAMES",
    "NODE_FEATURE_NAMES",
    "TRANSFORMS",
    "edge_transform_of",
    "global_transform_of",
    "node_transform_of",
    "FeatureScaler",
    "fit_scaler",
    "transform_window",
    "RawGraphWindow",
    "build_clip_windows",
    "window_bounds",
]
