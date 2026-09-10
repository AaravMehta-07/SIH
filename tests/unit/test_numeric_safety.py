"""MO05 (Appendix R.3): non-finite inputs fail explicitly.

Non-finite states or observations raise ``NonFiniteTensorError`` instead of
producing zero forecasts or silent NaN propagation (Build Spec H.5).
"""

from __future__ import annotations

import pytest
import torch

from conftest import build_candidates, build_clip, build_window, observed_state

from foresight.models.types import NonFiniteTensorError


def _clean_state(model):
    return observed_state(model, build_clip(num_windows=4, seed=61))


class TestMO05StateInputs:
    @pytest.mark.parametrize(
        "field",
        ["entity_memory", "global_h", "global_c", "global_context"],
    )
    def test_nan_state_raises(self, model, field):
        s = _clean_state(model).clone()
        with torch.no_grad():
            getattr(s, field)[...] = float("nan")
        with pytest.raises(NonFiniteTensorError):
            model.transition_prior(s)

    @pytest.mark.parametrize(
        "field",
        ["entity_memory", "global_h", "global_c", "global_context"],
    )
    def test_inf_state_raises(self, model, field):
        s = _clean_state(model).clone()
        with torch.no_grad():
            getattr(s, field)[...] = float("inf")
        with pytest.raises(NonFiniteTensorError):
            model.transition_prior(s)

    def test_nan_state_raises_at_decode(self, model):
        s = _clean_state(model).clone()
        with torch.no_grad():
            s.entity_memory[0, 1, 3] = float("nan")
        with pytest.raises(NonFiniteTensorError):
            model.decode_state(s, build_candidates())

    def test_nan_state_raises_at_observe(self, model):
        s = _clean_state(model).clone()
        w = build_window(seed=62)
        with torch.no_grad():
            s.global_context[0, 0] = float("nan")
        with pytest.raises(NonFiniteTensorError):
            model.observe_window(s, w)


class TestMO05WindowInputs:
    @pytest.mark.parametrize("field", ["x", "edge_attr", "global_raw"])
    def test_nan_window_raises(self, model, field):
        w = build_window(seed=63)
        with torch.no_grad():
            getattr(w, field)[...] = float("nan")
        state = model.zero_state(w.node_present)
        with pytest.raises(NonFiniteTensorError):
            model.observe_window(state, w)

    def test_nan_edge_attr_rejected(self, model):
        w = build_window(seed=64)
        w.edge_attr[0, 0] = float("nan")
        state = model.zero_state(w.node_present)
        with pytest.raises(NonFiniteTensorError):
            model.observe_window(state, w)

    def test_inf_node_feature_rejected(self, model):
        w = build_window(seed=65)
        w.x[0, 5] = float("inf")
        state = model.zero_state(w.node_present)
        with pytest.raises(NonFiniteTensorError):
            model.observe_window(state, w)

    def test_window_validate_reports_field_name(self):
        w = build_window(seed=66)
        w.x[1, 2] = float("nan")
        with pytest.raises(NonFiniteTensorError, match="x"):
            w.validate()


class TestMO05ErrorIsTyped:
    def test_nonfinite_is_typed_distinctly(self):
        """numeric_failure is a distinct health status from contract violations
        (Section 26), so the runtime can map each type separately."""
        from foresight.models.types import ContractError

        assert issubclass(NonFiniteTensorError, RuntimeError)
        assert not issubclass(NonFiniteTensorError, ContractError)
        assert not issubclass(ContractError, NonFiniteTensorError)

    def test_health_status_mapping(self, model):
        """A numeric failure is a health status, not a crash path (Section 26):
        the exception type is importable and distinct so callers can map it."""
        s = _clean_state(model).clone()
        with torch.no_grad():
            s.entity_memory[0, 0, 0] = float("nan")
        try:
            model.transition_prior(s)
        except NonFiniteTensorError as exc:
            message = str(exc)
            assert any(
                name in message
                for name in ("entity_memory", "global_h", "global_c", "global_context")
            )
        else:
            pytest.fail("NonFiniteTensorError not raised")

    def test_finite_state_passes_validation(self, model):
        s = _clean_state(model)
        s.validate_finite()  # must not raise

    def test_worldstate_zeros_is_finite(self, model):
        s = model.zero_state(torch.ones(2, 3, dtype=torch.bool))
        s.validate_finite()
