"""Training-target contract tests (Build Spec Appendix D.6, Section 15/I.2;
test TR01's data side and the TR02 split guard)."""

from __future__ import annotations

import pytest
import torch

from conftest import build_candidates, build_targets
from foresight.models.types import ContractError
from foresight.training.targets import ClipTargets, assert_trainable_split


class TestValidTargets:
    def test_default_build_validates(self):
        t = build_targets()
        assert t.num_nodes == 4
        assert t.horizon_bins == 60
        assert t.num_tasks == 5

    def test_event_stops_risk_bins(self):
        t = build_targets(event_specs={(0, 0): 5})
        assert t.event_y[0, 4, 0] == 1.0
        assert t.event_y[0, :, 0].sum() == 1.0
        assert t.risk_mask[0, :5, 0].all()
        assert not t.risk_mask[0, 5:, 0].any()

    def test_censored_row_truncated(self):
        t = build_targets(event_specs={(1, 2): 0}, censor_bins=30)
        assert t.event_y[1, :, 2].sum() == 0.0
        assert t.risk_mask[1, :30, 2].all()
        assert not t.risk_mask[1, 30:, 2].any()

    def test_event_at_first_bin(self):
        t = build_targets(event_specs={(3, 4): 1})
        assert t.event_y[3, 0, 4] == 1.0
        assert t.risk_mask[3, :, 4].sum() == 1


class TestValidation:
    def _base(self):
        return build_targets(horizon_bins=10, num_tasks=3)

    def test_two_events_rejected(self):
        t = self._base()
        bad = t.event_y.clone()
        bad[0, 2, 0] = 1.0
        bad[0, 5, 0] = 1.0
        with pytest.raises(ContractError, match="at most one"):
            ClipTargets(**{**t.__dict__, "event_y": bad})

    def test_event_beyond_mask_rejected(self):
        t = self._base()
        bad_y = t.event_y.clone()
        bad_y[0, 7, 0] = 1.0
        bad_m = t.risk_mask.clone()
        bad_m[0, :, 0] = False
        bad_m[0, :3, 0] = True
        with pytest.raises(ContractError, match="stop exactly"):
            ClipTargets(**{**t.__dict__, "event_y": bad_y, "risk_mask": bad_m})

    def test_non_contiguous_mask_rejected(self):
        t = self._base()
        bad = t.risk_mask.clone()
        bad[0, 3, 0] = False
        bad[0, 4, 0] = True
        with pytest.raises(ContractError, match="contiguous"):
            ClipTargets(**{**t.__dict__, "risk_mask": bad})

    def test_nonbinary_event_y_rejected(self):
        t = self._base()
        bad = t.event_y.clone()
        bad[0, 0, 0] = 0.5
        with pytest.raises(ContractError, match="0/1"):
            ClipTargets(**{**t.__dict__, "event_y": bad})

    def test_wrong_shape_rejected(self):
        t = self._base()
        with pytest.raises(ContractError):
            ClipTargets(**{**t.__dict__, "stage_labels": torch.zeros(4, 10, 3)})

    def test_task_count_mismatch_rejected(self):
        t = self._base()
        with pytest.raises(ContractError, match="num_event_tasks"):
            ClipTargets(**{**t.__dict__, "num_event_tasks": 7})

    def test_edge_rows_must_match_candidates(self):
        t = self._base()
        other = build_candidates(pairs=[(0, 0, 1)])
        with pytest.raises(ContractError, match="candidate"):
            ClipTargets(**{**t.__dict__, "candidate_pairs": other})

    def test_unknown_split_rejected(self):
        t = self._base()
        with pytest.raises(ContractError, match="split"):
            ClipTargets(**{**t.__dict__, "split": "validation"})


class TestTR02SplitGuard:
    @pytest.mark.parametrize("split", ["test", "locked_test"])
    def test_non_trainable_splits_refused(self, split):
        with pytest.raises(ContractError, match="never be opened"):
            assert_trainable_split(split)

    @pytest.mark.parametrize("split", ["train", "development", "calibration"])
    def test_trainable_splits_allowed(self, split):
        assert_trainable_split(split)

    def test_unknown_split_refused(self):
        with pytest.raises(ContractError, match="unknown split"):
            assert_trainable_split("oops")
