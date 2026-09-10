"""MO02 (Appendix R.3): LSTM state round-trip and recurrent-state integrity."""

from __future__ import annotations

import torch

from conftest import build_clip, build_window, observed_state


def _snapshot(state) -> dict:
    return {
        "entity_memory": state.entity_memory.clone(),
        "global_h": state.global_h.clone(),
        "global_c": state.global_c.clone(),
        "global_context": state.global_context.clone(),
    }


def _assert_equal(a: dict, b: dict) -> None:
    for key in a:
        assert torch.equal(a[key], b[key]), f"{key} diverged"


class TestMO02LstmStateRoundTrip:
    def test_checkpoint_round_trip(self, core_config, model):
        """Saving and restoring the module reproduces outputs exactly."""
        from foresight.models.world_model import ForesightWorldModel

        clip = build_clip(num_windows=6, seed=41)
        with torch.no_grad():
            state = observed_state(model, clip)
            out_a = model.decode_state(state, None)

        torch.manual_seed(999)
        other = ForesightWorldModel.from_config(core_config, num_event_tasks=5)
        other.eval()
        with torch.no_grad():
            out_before = other.decode_state(observed_state(other, clip), None)
        assert not torch.allclose(out_before.hazard_logits, out_a.hazard_logits)

        other.load_state_dict(model.state_dict())
        with torch.no_grad():
            out_after = other.decode_state(observed_state(other, clip), None)
        assert torch.equal(out_after.hazard_logits, out_a.hazard_logits)
        assert torch.equal(out_after.node_mean, out_a.node_mean)

    def test_both_lstm_layers_populated(self, model):
        """After >= 2 observed windows both layer-0 and layer-1 h/c states are
        nonzero — the two-layer LSTM actually recurs, not just layer 0."""
        clip = build_clip(num_windows=5, seed=42)
        s = observed_state(model, clip)
        for name, t in [("global_h[0]", s.global_h[0]), ("global_h[1]", s.global_h[1]),
                        ("global_c[0]", s.global_c[0]), ("global_c[1]", s.global_c[1])]:
            assert torch.count_nonzero(t) > 0, f"{name} stayed at zero"

    def test_state_changes_every_window(self, model):
        clip = build_clip(num_windows=4, seed=43)
        state = model.zero_state(clip[0].node_present)
        seen = []
        for w in clip:
            state = model.observe_window(state, w)
            seen.append(_snapshot(state))
        for i in range(1, len(seen)):
            _assert_not_equal(seen[i - 1], seen[i])

    def test_repeated_forward_deterministic(self, model):
        clip = build_clip(num_windows=6, seed=44)
        first = _snapshot(observed_state(model, clip))
        second = _snapshot(observed_state(model, clip))
        _assert_equal(first, second)


class TestMO02StateIsolation:
    def test_clone_is_independent(self, model):
        clip = build_clip(num_windows=4, seed=45)
        s = observed_state(model, clip)
        before = _snapshot(s)
        z = s.clone()
        for _ in range(3):
            z = model.transition_prior(z)
        _assert_equal(before, _snapshot(s))

    def test_clone_preserves_gradients(self, model):
        import dataclasses

        w = build_window(seed=46)
        leaf = w.x.clone().requires_grad_(True)
        w_grad = dataclasses.replace(w, x=leaf)
        s = model.observe_window(model.zero_state(w_grad.node_present), w_grad)
        z = s.clone()
        z.entity_memory.sum().backward()
        assert leaf.grad is not None
        assert torch.isfinite(leaf.grad).all()

    def test_transition_returns_new_storage(self, model):
        """transition_prior is functional: the input state's tensors are never
        aliased or mutated by the transitioned state."""
        clip = build_clip(num_windows=3, seed=47)
        s = observed_state(model, clip)
        frozen = s.clone()
        t = model.transition_prior(s)
        assert torch.equal(frozen.entity_memory, s.entity_memory)
        assert torch.equal(frozen.global_h, s.global_h)
        assert torch.equal(frozen.global_c, s.global_c)
        assert not torch.equal(t.entity_memory, s.entity_memory)
        assert t.entity_memory.data_ptr() != s.entity_memory.data_ptr()


def _assert_not_equal(a: dict, b: dict) -> None:
    assert any(not torch.equal(a[k], b[k]) for k in a)
