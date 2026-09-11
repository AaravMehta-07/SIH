"""Trained artifact bundle loading (Build Spec I.6, SE01).

Loads the Section-35 run bundle (``artifacts/profile``): member weights
(safetensors), calibrators, scaler, selection policy, task manifest, novelty
reference — verifying every recorded hash before use. A missing or corrupt
bundle is a typed artifact error; the server may fall back to untrained
reference weights ONLY with an explicit disclosure in every response (no
silent fallback, I.6).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import torch

from ..calibration.hazard import CalibratorSet, HazardCalibrator
from ..contracts.quality import NOT_SUPPORTED_WIRE
from ..features.transforms import FeatureScaler
from ..models.config import load_core_config
from ..models.variants import build_world_model
from ..models.world_model import ForesightWorldModel
from ..paths.engine import PathEngine, load_path_engine
from ..runtime.forecast import EnsembleForecaster, ForecastEngine
from ..sentinel.reference import NoveltyReference


class ArtifactError(RuntimeError):
    """Bundle missing, incomplete or hash-mismatched (I.6)."""


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class RuntimeBundle:
    """Verified bundle + the serving ensemble built from it."""

    root: Path
    manifest: dict
    scaler: FeatureScaler
    engines: list[ForecastEngine]
    ensemble: EnsembleForecaster
    selection_policy: dict
    task_manifest: list[dict]
    novelty_reference: NoveltyReference | None
    seeds: tuple[int, ...]
    trained: bool
    weights_profile: str
    novelty_note: str = "reference fitted on benign training clips"
    members: list[tuple[str, int]] = None  # I.5: [(variant, seed), ...]
    path_engine: PathEngine | None = None   # Tier B §20 when trained

    def __post_init__(self) -> None:
        if self.members is None:
            self.members = [("reference", s) for s in self.seeds]

    @property
    def params_per_member(self) -> int:
        return sum(
            p.numel() for p in self.engines[0].model.parameters()
        )

    def policy_threshold(self, task_index: int) -> float | None:
        entry = self.selection_policy.get(str(task_index))
        if not entry or entry.get("status") != "supported":
            return None
        return entry.get("threshold")


def load_bundle(
    root: Path, *, config_path: Path | None = None
) -> RuntimeBundle:
    """Load and verify a trained bundle, or the disclosed untrained fallback."""
    config = load_core_config(config_path) if config_path else load_core_config(
        root.parents[1] / "configs" / "core.yaml"
    )

    required = [
        "manifest.json", "scaler.json", "calibrators.json",
        "selection_policy.json", "task_manifest.json",
    ]
    if not root.is_dir() or not all((root / f).exists() for f in required):
        return _untrained_fallback(root, config)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    hashes = json.loads(
        (root / "artifact_hashes.json").read_text(encoding="utf-8")
    ) if (root / "artifact_hashes.json").exists() else {}

    # SE01: verify every recorded hash before accepting the bundle.
    for name, expected in hashes.items():
        path = root / name
        if not path.exists():
            raise ArtifactError(f"bundle file missing: {name}")
        if _sha256_file(path) != expected:
            raise ArtifactError(f"bundle hash mismatch: {name}")

    scaler = FeatureScaler.from_json(
        json.loads((root / "scaler.json").read_text(encoding="utf-8"))
    )
    calibrators = json.loads(
        (root / "calibrators.json").read_text(encoding="utf-8")
    )
    policy = json.loads(
        (root / "selection_policy.json").read_text(encoding="utf-8")
    )
    task_manifest = json.loads(
        (root / "task_manifest.json").read_text(encoding="utf-8")
    )
    seeds = tuple(manifest.get("seeds", [0, 1, 2]))
    # I.5 heterogeneous members: manifest["members"] names each member's
    # variant; legacy reference-only bundles fall back to the seeds list.
    members: list[tuple[str, int]] = [
        (str(m.get("variant", "reference")), int(m["seed"]))
        for m in manifest.get("members", [])
    ] or [("reference", s) for s in seeds]

    def _member_weights(variant: str, seed: int) -> dict:
        path = root / f"model_{variant}_seed{seed}.safetensors"
        if not path.exists() and variant == "reference":
            path = root / f"model_seed{seed}.safetensors"
        if not path.exists():
            raise ArtifactError(f"member weights missing: {variant}:{seed}")
        name = path.name
        if name in hashes:
            if _sha256_file(path) != hashes[name]:
                raise ArtifactError(f"bundle hash mismatch: {name}")
        from safetensors.torch import load_file

        return load_file(str(path))

    def _member_calibrators(variant: str, seed: int) -> CalibratorSet:
        # member-qualified keys "{variant}:{seed}:{task}"; legacy reference
        # bundles use "{seed}:{task}".
        cals = {
            (int(k.split(":")[2]), None): HazardCalibrator.from_dict(v)
            for k, v in calibrators.items()
            if k.startswith(f"{variant}:{seed}:")
        }
        if not cals and variant == "reference":
            cals = {
                (int(k.split(":")[1]), None): HazardCalibrator.from_dict(v)
                for k, v in calibrators.items()
                if k.count(":") == 1 and int(k.split(":")[0]) == seed
            }
        return CalibratorSet(calibrators=cals, pooled=None)

    engines: list[ForecastEngine] = []
    variant_counts: dict[str, int] = {}
    for variant, seed in members:
        model = build_world_model(config, variant=variant, num_event_tasks=5)
        model.load_state_dict(_member_weights(variant, seed))
        model.eval()
        variant_counts[variant] = variant_counts.get(variant, 0) + 1
        engines.append(
            ForecastEngine(model, calibrator_set=_member_calibrators(variant, seed))
        )

    novelty = None
    novelty_path = root / "novelty_reference.npz"
    if novelty_path.exists():
        novelty = NoveltyReference.from_npz(novelty_path)

    run = {}
    run_path = root / "training_run.json"
    if run_path.exists():
        run = json.loads(run_path.read_text(encoding="utf-8"))

    seeds = tuple(s for v, s in members if v == "reference") or tuple(
        s for _, s in members
    )
    hetero = "+".join(
        f"{v}x{n}" for v, n in sorted(variant_counts.items())
    )
    profile = (
        f"Section-35 trained profile (I.5 heterogeneous ensemble: {hetero}, "
        f"{'synthetic corpus, disclosed' if manifest.get('synthetic_data_only') else 'undisclosed data'}"
        f"; best epochs "
        + ", ".join(
            str(
                run.get("seeds", {}).get(f"{v}:{s}", {}).get(
                    "best_epoch",
                    run.get("seeds", {}).get(str(s), {}).get("best_epoch", "?"),
                )
            )
            for v, s in members
        )
        + ") with I.4 natural-prevalence calibration - interface semantics "
        "on synthetic data, not measured real-world performance"
    )
    return RuntimeBundle(
        root=root,
        manifest=manifest,
        scaler=scaler,
        engines=engines,
        ensemble=EnsembleForecaster(engines),
        selection_policy=policy,
        task_manifest=task_manifest,
        novelty_reference=novelty,
        seeds=seeds,
        trained=True,
        weights_profile=profile,
        members=members,
        path_engine=load_path_engine(root.parents[1] / "artifacts" / "paths"),
    )


def _untrained_fallback(root: Path, config) -> RuntimeBundle:
    engines = []
    for seed in (0, 1, 2):
        torch.manual_seed(seed)
        model = ForesightWorldModel.from_config(config, num_event_tasks=5)
        model.eval()
        engines.append(ForecastEngine(model))
    from ..labels.ontology import TASK_DEFINITIONS

    return RuntimeBundle(
        root=root,
        manifest={"profile": "untrained-fallback"},
        scaler=_unit_scaler(),
        engines=engines,
        ensemble=EnsembleForecaster(engines),
        selection_policy={},
        task_manifest=[
            {
                "task_index": t.task_index,
                "id": t.id,
                "label": t.label,
                "label_tier": t.label_tier,
                "description": t.description,
            }
            for t in TASK_DEFINITIONS
        ],
        novelty_reference=None,
        seeds=(0, 1, 2),
        trained=False,
        weights_profile=(
            "UNTRAINED reference weights (no artifacts/profile bundle found): "
            "forecasts illustrate interface semantics only - run "
            "scripts/train_profile.py to produce the trained profile"
        ),
        novelty_note="novelty unavailable (no trained reference)",
    )


def _unit_scaler() -> FeatureScaler:
    """Identity-ish scaler for the untrained fallback (med 0, IQR 1)."""
    import numpy as np

    return FeatureScaler(
        node_median=np.zeros(44),
        node_iqr=np.ones(44),
        node_supported=np.ones(44, dtype=bool),
        edge_median=np.zeros(11),
        edge_iqr=np.ones(11),
        edge_supported=np.ones(11, dtype=bool),
        global_median=np.zeros(24),
        global_iqr=np.ones(24),
        global_supported=np.ones(24, dtype=bool),
    )
