"""Calibration package (Build Spec Appendix I.4, C.2).

Public surface:
- :class:`HazardCalibrator` — the affine (slope + intercept + horizon-group
  intercepts) discrete-hazard calibrator.
- :func:`fit_hazard_calibrator` — survival-likelihood fit on the calibration
  split, with pooled/abstain backoff for sparse cells.
- :class:`CalibratorSet` — the Appendix-S ``calibrate(logits, task, regime)``
  interface used by the runtime.
"""

from .hazard import (
    DEFAULT_FIT_MAX_ITER,
    DEFAULT_GROUP_L2,
    DEFAULT_MIN_EVENTS,
    HORIZON_GROUPS,
    CalibratorSet,
    HazardCalibrator,
    calibration_support,
    fit_hazard_calibrator,
    horizon_group_index,
    horizon_group_vector,
)

__all__ = [
    "DEFAULT_FIT_MAX_ITER",
    "DEFAULT_GROUP_L2",
    "DEFAULT_MIN_EVENTS",
    "HORIZON_GROUPS",
    "CalibratorSet",
    "HazardCalibrator",
    "calibration_support",
    "fit_hazard_calibrator",
    "horizon_group_index",
    "horizon_group_vector",
]
