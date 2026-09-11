"""Fine-tune and evaluate the qualified CTU-13 transfer profile.

The scenario split is frozen in ``configs/datasets/ctu13.json`` before any
locked-test evaluation.  Scenario 1 trains, scenario 6 calibrates, and
scenario 12 is locked.  Labels never enter serving windows (Sections 6-11,
M.1); only task 0 and explicitly marked C2 task 3 are qualified.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import load_file, save_file

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from foresight.calibration.hazard import (  # noqa: E402
    CalibratorSet,
    HazardCalibrator,
    fit_hazard_calibrator,
)
from foresight.data.clips import ClipDataset  # noqa: E402
from foresight.data.ctu import build_ctu_episode  # noqa: E402
from foresight.evaluation.report import evaluate_locked_test  # noqa: E402
from foresight.ingest.ctu_adapter import parse_ctu_binetflow  # noqa: E402
from foresight.labels.ontology import TASK_DEFINITIONS  # noqa: E402
from foresight.models.config import load_core_config  # noqa: E402
from foresight.models.variants import build_world_model  # noqa: E402
from foresight.runtime.forecast import ForecastEngine  # noqa: E402
from foresight.training.trainer import Trainer  # noqa: E402
from train_profile import (  # noqa: E402
    candidates_to_device,
    collect_cal_records,
    fit_selection_policy,
    predict_locked_test,
    targets_to_device,
    to_device,
)

MEMBERS = (("reference", 0), ("gate", 0), ("wide", 0))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_registry(registry: dict) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for entry in registry["files"]:
        if entry["kind"] != "binetflow":
            continue
        path = REPO_ROOT / entry["local_artifact"]
        if not path.exists():
            raise FileNotFoundError(f"missing registered object: {path}")
        if path.stat().st_size != int(entry["size_bytes"]):
            raise ValueError(f"registered size mismatch: {path.name}")
        if sha256_file(path) != entry["sha256"]:
            raise ValueError(f"registered SHA-256 mismatch: {path.name}")
        paths[entry["role"]] = path
    return paths


def load_scenario_episodes(path: Path, scenario: str, *, max_slices: int) -> list:
    print(f"parsing CTU-13 scenario {scenario}: {path.name}", flush=True)
    parsed = parse_ctu_binetflow(path, scenario_id=scenario)
    episodes = []
    for slice_index in range(max_slices):
        try:
            # Both fixed /25 cohorts are retained. They are correlated views of
            # one scenario and are never counted as independent campaigns.
            episodes.extend(
                build_ctu_episode(parsed, partition=partition, slice_index=slice_index)
                for partition in (0, 1)
            )
        except ValueError:
            break
    print(
        f"  accepted={parsed.stream.quality.accepted_records} "
        f"malformed={parsed.stream.quality.rejected_malformed} "
        f"episodes={len(episodes)} labels={len(parsed.labels)}",
        flush=True,
    )
    return episodes


def source_weight_path(source: Path, variant: str, seed: int) -> Path:
    path = source / f"model_{variant}_seed{seed}.safetensors"
    if not path.exists() and variant == "reference":
        path = source / f"model_seed{seed}.safetensors"
    if not path.exists():
        raise FileNotFoundError(f"source member missing: {variant}:{seed}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=REPO_ROOT / "artifacts" / "profile")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "artifacts" / "ctu13" / "profile")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    if args.epochs < 1:
        raise ValueError("epochs must be positive")

    registry_path = REPO_ROOT / "configs" / "datasets" / "ctu13.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    paths = verify_registry(registry)
    args.out.mkdir(parents=True, exist_ok=True)
    cache = REPO_ROOT / "artifacts" / "ctu13" / "cache"
    config = load_core_config(REPO_ROOT / "configs" / "core.yaml")
    device = torch.device(args.device)
    print(f"device={device}; fixed transfer members={MEMBERS}", flush=True)

    train_episodes = load_scenario_episodes(paths["train"], "01", max_slices=8)
    train_raw = ClipDataset(train_episodes, split="train", scaler=None, stride=10)
    scaler = train_raw.fit_scaler_from_train()
    train_examples = ClipDataset(
        train_episodes, split="train", scaler=scaler, cache_dir=cache, stride=10
    ).examples()
    print(f"training clips={len(train_examples)}", flush=True)

    states: dict[tuple[str, int], dict[str, torch.Tensor]] = {}
    training_log: dict[str, object] = {
        "epochs": args.epochs,
        "horizon_bins": 10,
        "sampling": "natural CTU prevalence; background excluded from risk sets",
        "members": {},
    }
    for variant, seed in MEMBERS:
        model = build_world_model(config, variant=variant, num_event_tasks=5).to(device)
        model.load_state_dict(load_file(str(source_weight_path(args.source, variant, seed))))
        trainer = Trainer.from_config(model, config, seed=seed)
        losses = []
        for epoch in range(1, args.epochs + 1):
            order = np.random.default_rng(seed * 1000 + epoch).permutation(len(train_examples))
            epoch_losses = []
            for index in order:
                example = train_examples[int(index)]
                log = trainer.train_step(
                    [to_device(window, device) for window in example.windows],
                    targets_to_device(example.targets, device),
                    epoch=epoch,
                    horizon_bins=10,
                )
                epoch_losses.append(float(log.loss["total"]))
            mean_loss = float(np.mean(epoch_losses)) if epoch_losses else float("nan")
            losses.append(mean_loss)
            print(f"  {variant}:{seed} epoch={epoch} loss={mean_loss:.5f}", flush=True)
        states[(variant, seed)] = {
            key: value.detach().cpu().contiguous() for key, value in model.state_dict().items()
        }
        training_log["members"][f"{variant}:{seed}"] = {"epoch_mean_loss": losses}
        del model, trainer
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()

    del train_examples, train_raw
    gc.collect()
    cal_episodes = load_scenario_episodes(paths["calibration"], "06", max_slices=3)
    cal_examples = ClipDataset(
        cal_episodes, split="calibration", scaler=scaler, cache_dir=cache, stride=10
    ).examples()
    engines = []
    calibrators_payload: dict[str, dict] = {}
    models = []
    for variant, seed in MEMBERS:
        model = build_world_model(config, variant=variant, num_event_tasks=5).to(device)
        model.load_state_dict({k: v.to(device) for k, v in states[(variant, seed)].items()})
        model.eval()
        models.append(model)
        engine = ForecastEngine(model)
        _, logits = collect_cal_records([engine], device, cal_examples)
        cals = {}
        for task, (raw_logits, events, masks) in logits.items():
            cal = fit_hazard_calibrator(raw_logits, events, masks, task_index=task)
            calibrators_payload[f"{variant}:{seed}:{task}"] = cal.to_dict()
            cals[(task, None)] = cal
        engine.calibrator_set = CalibratorSet(calibrators=cals, pooled=None)
        engines.append(engine)
    cal_records, _ = collect_cal_records(engines, device, cal_examples)
    policy = fit_selection_policy(cal_records)
    for task in (0, 3):
        policy.setdefault(
            str(task),
            {"threshold": None, "status": "insufficient_positive_support",
             "false_alerts_per_100_asset_hours": None, "total_events": 0},
        )
    print(f"selection policy={policy}", flush=True)

    del cal_examples, cal_episodes
    gc.collect()
    test_episodes = load_scenario_episodes(paths["locked-test"], "12", max_slices=2)
    test_examples = ClipDataset(
        test_episodes, split="locked_test", scaler=scaler, cache_dir=cache, stride=10
    ).examples()
    predictions = predict_locked_test(engines, device, test_examples)

    # M.2 empirical hazard uses CTU scenario 1 only. Rebuild just the compact
    # target tensors from cached train clips; no calibration/test observations.
    train_examples = ClipDataset(
        train_episodes, split="train", scaler=scaler, cache_dir=cache, stride=10
    ).examples()
    train_event_y = torch.cat([example.targets.event_y for example in train_examples], dim=0).numpy()
    train_risk_mask = torch.cat([example.targets.risk_mask for example in train_examples], dim=0).numpy()
    report = evaluate_locked_test(
        predictions,
        policy,
        train_event_y=train_event_y,
        train_risk_mask=train_risk_mask,
        independent_units=1,
    )
    report.note = (
        "CTU-13 real-network transfer stress. Scenario 1 trained, scenario 6 "
        "calibrated, and scenario 12 was locked before evaluation. Background "
        "is excluded from benign negatives. Public labels do not provide a "
        "forecastable onset in every scenario, so event gates may be inconclusive."
    )

    for variant, seed in MEMBERS:
        save_file(states[(variant, seed)], str(args.out / f"model_{variant}_seed{seed}.safetensors"))
    (args.out / "scaler.json").write_text(json.dumps(scaler.to_json(), indent=2), encoding="utf-8")
    (args.out / "calibrators.json").write_text(json.dumps(calibrators_payload, indent=2), encoding="utf-8")
    (args.out / "selection_policy.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
    (args.out / "test_predictions.json").write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    (args.out / "evaluation_report.json").write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    task_manifest = [
        {
            "task_index": task.task_index,
            "id": task.id,
            "label": task.label,
            "label_tier": task.label_tier,
            "description": task.description,
            "ctu_status": "supported" if task.task_index in (0, 3) else "not_supported",
        }
        for task in TASK_DEFINITIONS
    ]
    (args.out / "task_manifest.json").write_text(json.dumps(task_manifest, indent=2), encoding="utf-8")
    manifest = {
        "schema": "foresight.core.2026-09",
        "profile": "ctu13-real-flow-transfer-v1",
        "synthetic_data_only": False,
        "source_profile_manifest_sha256": sha256_file(args.source / "manifest.json"),
        "dataset_registry_sha256": sha256_file(registry_path),
        "members": [{"variant": variant, "seed": seed} for variant, seed in MEMBERS],
        "seeds": [0],
        "split_unit": "CTU scenario/campaign",
        "splits": registry["split_policy"],
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (args.out / "training_run.json").write_text(json.dumps(training_log, indent=2), encoding="utf-8")
    hash_names = [path.name for path in args.out.iterdir() if path.is_file() and path.name != "artifact_hashes.json"]
    hashes = {name: sha256_file(args.out / name) for name in sorted(hash_names)}
    (args.out / "artifact_hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")

    print(f"CTU profile -> {args.out}")
    print("gates:")
    for gate in report.gates:
        print(f"  {gate.status.upper():12s} {gate.name}: {gate.value} ({gate.reason})")


if __name__ == "__main__":
    main()
