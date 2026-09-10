"""Locked-test evaluation over the trained bundle (Build Spec M.1-M.5).

Reads the frozen ``test_predictions.json`` + ``selection_policy.json`` from
the Section-35 bundle, rebuilds the corpus splits for asset-hours and
baseline fitting, and writes ``evaluation_report.json`` (M.5: gates with
pass/fail/inconclusive, sample sizes, per-family/per-task slices, bootstrap
intervals). Honest reporting: synthetic-corpus evidence only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from foresight.data.clips import ClipDataset  # noqa: E402
from foresight.data.episodes import build_corpus  # noqa: E402
from foresight.data.splits import split_episodes  # noqa: E402
from foresight.evaluation.report import evaluate_locked_test  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=REPO_ROOT / "artifacts" / "profile")
    parser.add_argument("--seed-base", type=int, default=0)
    args = parser.parse_args()

    predictions_path = args.bundle / "test_predictions.json"
    policy_path = args.bundle / "selection_policy.json"
    if not predictions_path.exists():
        print("no test_predictions.json in bundle - run scripts/train_profile.py first")
        raise SystemExit(2)
    predictions = json.loads(predictions_path.read_text(encoding="utf-8"))
    policy = json.loads(policy_path.read_text(encoding="utf-8"))

    print(f"predictions: {len(predictions)} records", flush=True)

    # Baselines need the training split's event/risk tables (M.2).
    print("rebuilding corpus for baseline tables...", flush=True)
    episodes = build_corpus(seed_base=args.seed_base)
    splits = split_episodes(episodes)
    train_ds = ClipDataset(list(splits.train), split="train", scaler=None)
    scaler = train_ds.fit_scaler_from_train()
    train = ClipDataset(
        list(splits.train), split="train", scaler=scaler
    ).examples()
    event_y = torch.stack([ex.targets.event_y for ex in train])
    risk_mask = torch.stack([ex.targets.risk_mask for ex in train])

    report = evaluate_locked_test(
        predictions,
        policy,
        train_event_y=event_y.numpy(),
        train_risk_mask=risk_mask.numpy(),
    )
    out_path = args.bundle / "evaluation_report.json"
    report.save(out_path)
    print(f"report -> {out_path}")

    print("\n== gates ==")
    for gate in report.gates:
        print(
            f"  {gate.status.upper():14s} {gate.name}"
            f" (value={gate.value}, threshold={gate.threshold})"
            + (f" - {gate.reason}" if gate.reason else "")
        )
    m = report.metrics
    print("\n== metrics ==")
    print(f"  event recall:        {m['event_recall']:.3f}")
    print(f"  precision:           {m['precision']:.3f}")
    print(f"  false alerts/100ah:  {m['false_alerts_per_100_asset_hours']:.2f}")
    print(f"  AP (primary):        {m['average_precision_primary']:.3f}")
    print(f"  Brier @300s:         {m['brier_300s']:.4f} (n={m['brier_n']})")
    print(f"  ECE @300s:           {m['ece_300s']:.4f}")
    print(f"  matched/missed:      {m['matched_events']}/{m['missed_events']}")
    if m["lead_time_seconds_median"] is not None:
        print(f"  median lead time:    {m['lead_time_seconds_median']:.0f}s")
    print("\n== per task ==")
    for t, row in report.per_task.items():
        print(f"  task {t}: {row}")


if __name__ == "__main__":
    main()
