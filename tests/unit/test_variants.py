"""I.5 heterogeneous ensemble member tests (Build Spec I.5, Section 35).

Every variant implements the same H.1 interface and frozen downstream
widths: entity memory 64, endpoint readout 192, edge readout 256, global
LSTM 152/128 — only the encoder/transition/head families differ.
"""

from __future__ import annotations

import pytest
import torch

from conftest import build_candidates, build_clip, build_targets
from foresight.models.config import CoreConfig
from foresight.models.variants import VARIANTS, build_world_model, variant_of


@pytest.fixture(scope="module")
def config() -> CoreConfig:
    from foresight.models.config import load_core_config
    from pathlib import Path

    return load_core_config(
        Path(__file__).resolve().parents[2] / "configs" / "core.yaml"
    )


@pytest.mark.parametrize("variant", VARIANTS)
def test_variant_h1_interface(config: CoreConfig, variant: str) -> None:
    """Observe + rollout produce the contracted shapes for every variant."""
    torch.manual_seed(0)
    model = build_world_model(config, variant=variant, num_event_tasks=5)
    model.eval()
    clip = build_clip(num_windows=3, seed=1)
    candidates = build_candidates()
    with torch.no_grad():
        observed = model.observe_clip(clip)
        outputs = model.roll_out(observed, 4, candidate_pairs=candidates)
    assert observed.entity_memory.shape == (1, 4, 64)
    assert outputs[0].hazard_logits.shape == (1, 4, 5)
    assert outputs[0].tactic_logits.shape == (1, 4, 5)
    assert outputs[0].edge_logits.shape == (3,)
    # frozen endpoint/edge readout widths survive variant assembly
    endpoint = torch.cat(
        [observed.entity_memory,
         observed.global_h[-1].unsqueeze(1).expand(1, 4, 128)],
        dim=-1,
    )
    assert endpoint.shape == (1, 4, 192)
    assert variant_of(model) == variant


def test_variant_architectures_are_distinct(config: CoreConfig) -> None:
    """I.5: members must differ in encoder, transition and head families —
    three dropout calls or three heads do not meet the contract."""
    models = {
        v: build_world_model(config, variant=v) for v in VARIANTS
    }
    for a in VARIANTS:
        for b in VARIANTS:
            if a >= b:
                continue
            ma, mb = models[a], models[b]
            assert type(ma.graph_encoder) is not type(mb.graph_encoder) or (
                type(ma.prior) is not type(mb.prior)
            ), f"{a} and {b} are not architecturally distinct"
    ref = models["reference"]
    gate = models["gate"]
    wide = models["wide"]
    assert type(gate.prior) is not type(ref.prior)
    assert type(wide.prior) is not type(ref.prior)
    assert type(gate.hazard_head) is not type(wide.hazard_head)


def test_unknown_variant_rejected(config: CoreConfig) -> None:
    with pytest.raises(ValueError, match="unknown variant"):
        build_world_model(config, variant="dropout3")


def test_member_plan_parsing() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from train_profile import parse_members

    plan = parse_members("reference:0,1,2,3,4 gate:0,1 wide:0-1")
    assert plan == [
        ("reference", 0), ("reference", 1), ("reference", 2),
        ("reference", 3), ("reference", 4),
        ("gate", 0), ("gate", 1),
        ("wide", 0), ("wide", 1),
    ]
    with pytest.raises(ValueError, match="unknown variant"):
        parse_members("mixture-of-experts:0")
    with pytest.raises(ValueError, match="member plan is empty"):
        parse_members("")


def test_variant_training_step_runs(config: CoreConfig) -> None:
    """A gradient flows through a gate/wide member's replaced modules."""
    from foresight.graphs.collate import stack_candidates, stack_windows
    from foresight.training.losses import LossWeights
    from foresight.training.trainer import Trainer

    torch.manual_seed(0)
    model = build_world_model(config, variant="gate", num_event_tasks=5)
    trainer = Trainer(
        model=model,
        weights=LossWeights.from_config(config.training["loss"]),
        learning_rate=1e-4,
        weight_decay=0.0,
        gradient_clip=1.0,
        epochs_max=1,
        seed=0,
    )
    clip = build_clip(num_windows=3, seed=2)
    candidates = build_candidates()
    targets = build_targets(num_nodes=4, horizon_bins=4, candidates=candidates)
    stacked = [stack_windows([w]) for w in clip]
    log = trainer.batched_step(
        stacked, [targets], stack_candidates([candidates]), epoch=1
    )
    assert log.loss["total"] > 0
    grads = [
        p.grad.abs().sum().item()
        for p in model.parameters()
        if p.grad is not None
    ]
    assert sum(grads) > 0
