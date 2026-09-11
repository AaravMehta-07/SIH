"""Command entry points (Build Spec Appendix L.4).

Proposed interface implemented as an argparse dispatcher; each subcommand
delegates to the module that owns the behavior. ``doctor`` checks
dependencies, parser capability, artifact hashes and the golden fixture
without training or downloading anything. Training/labels commands are not
available through the public serving API (L.4); they live here.

Exit codes: 0 success, 2 invalid input, 3 missing dependency, 4 failed gate,
5 inconclusive evaluation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_INVALID_INPUT = 2
EXIT_MISSING_DEPENDENCY = 3
EXIT_FAILED_GATE = 4
EXIT_INCONCLUSIVE = 5


def _repo_root() -> Path:
    # src/foresight/cli/__init__.py -> repo root is four levels up
    return Path(__file__).resolve().parents[3]


def cmd_doctor(args) -> int:
    """L.4 doctor: dependencies, artifact hashes, golden fixture."""
    from foresight.api.bundle import ArtifactError, load_bundle
    from foresight.models.survival import distribution_from_hazards
    import torch

    checks = []
    ok = True

    checks.append(
        {
            "check": "torch",
            "ok": True,
            "detail": f"{torch.__version__} (cuda={torch.cuda.is_available()})",
        }
    )
    for module in ("torch_geometric", "fastapi", "safetensors", "numpy"):
        try:
            __import__(module)
            checks.append({"check": module, "ok": True, "detail": ""})
        except ImportError as exc:
            ok = False
            checks.append({"check": module, "ok": False, "detail": str(exc)})

    # Golden fixture: Section 35 golden example 1 (R.2).
    hazards = torch.tensor([0.10, 0.20, 0.30], dtype=torch.float64)
    dist = distribution_from_hazards(hazards, bin_seconds=30)
    golden_ok = (
        all(
            abs(a - b) < 1e-9
            for a, b in zip(dist.cumulative_risk, [0.10, 0.28, 0.496])
        )
        and abs(float(dist.no_event_mass) - 0.504) < 1e-9
    )
    checks.append(
        {"check": "golden_fixture_r2", "ok": golden_ok, "detail": "hazards [0.1,0.2,0.3]"}
    )
    ok = ok and golden_ok

    profile_dir = _repo_root() / "artifacts" / "profile"
    try:
        bundle = load_bundle(profile_dir)
        checks.append(
            {
                "check": "artifact_bundle",
                "ok": True,
                "detail": (
                    "trained" if bundle.trained else
                    "untrained fallback (run scripts/train_profile.py)"
                ),
            }
        )
        checks.append(
            {
                "check": "tier_b_paths",
                "ok": True,
                "detail": (
                    "trained (Section 20 next-mark decoder)"
                    if bundle.path_engine is not None
                    else "not trained (typed paths report not_supported; "
                    "run scripts/train_paths.py)"
                ),
            }
        )
    except ArtifactError as exc:
        ok = False
        checks.append({"check": "artifact_bundle", "ok": False, "detail": str(exc)})

    for c in checks:
        mark = "OK " if c["ok"] else "FAIL"
        print(f"[{mark}] {c['check']}: {c['detail']}")
    return 0 if ok else EXIT_FAILED_GATE


def cmd_train(args) -> int:
    scripts = _repo_root() / "scripts"
    sys.path.insert(0, str(scripts))
    from train_profile import main as train_main

    sys.argv = [
        "train",
        "--out", args.out,
        "--cache", args.cache,
        "--seeds", *map(str, args.seeds),
        "--epochs", str(args.epochs),
    ]
    if args.device:
        sys.argv += ["--device", args.device]
    train_main()
    return 0


def cmd_evaluate(args) -> int:
    scripts = _repo_root() / "scripts"
    sys.path.insert(0, str(scripts))
    from evaluate_profile import main as evaluate_main

    sys.argv = ["evaluate", "--bundle", args.bundle]
    evaluate_main()
    return 0


def cmd_serve(args) -> int:
    import os

    import uvicorn

    uvicorn.run(
        "foresight.api.server:app",
        host="127.0.0.1",
        port=args.port or int(os.environ.get("FORESIGHT_CONSOLE_PORT", "8001")),
        log_level="info",
    )
    return 0


def cmd_bundle_verify(args) -> int:
    from foresight.api.bundle import ArtifactError, load_bundle

    try:
        bundle = load_bundle(Path(args.bundle))
    except ArtifactError as exc:
        print(f"FAIL: {exc}")
        return EXIT_FAILED_GATE
    print(
        f"OK: bundle verified at {args.bundle} "
        f"(trained={bundle.trained}, seeds={list(bundle.seeds)}, "
        f"members={len(bundle.engines)})"
    )
    return 0


def cmd_replay_predict(args) -> int:
    """L.4 replay predict: one sealed forecast for an episode/cutoff."""
    import torch

    from foresight.api.bundle import load_bundle
    from foresight.data.clips import build_serving_windows, precompute_episode
    from foresight.data.episodes import build_episode
    from foresight.runtime.forecast import ForecastRequest

    bundle = load_bundle(Path(args.bundle))
    episode = build_episode(args.episode.split(":")[0], int(args.episode.split(":")[1]))
    pre = precompute_episode(episode)
    cutoff = args.cutoff or max(pre.prefix_windows)
    windows, candidates = build_serving_windows(pre, bundle.scaler, cutoff)
    request = ForecastRequest(
        horizon_bins=60,
        bin_seconds=30,
        task_mask=torch.ones(5, dtype=torch.bool),
        min_occurrence_probability=0.30,
        published_horizons_seconds=(300, 900, 1800),
        candidate_pairs=candidates,
    )
    result = bundle.ensemble.forecast(windows, request)
    out = {
        "episode": episode.episode_id,
        "cutoff_window": cutoff,
        "weights_profile": bundle.weights_profile,
        "entities": [
            {
                "name": pre.entity_ids[e.slot],
                "occurrence_300s": (
                    round(float(e.task_forecasts[2].distribution.cumulative_risk[9]), 6)
                    if e.task_forecasts[2].distribution is not None
                    else None
                ),
            }
            for e in result.entities
        ],
    }
    print(json.dumps(out, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foresight", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="check dependencies and artifacts")
    p.add_argument("--config", default="configs/core.yaml")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("train", help="Section-35 training run")
    p.add_argument("--out", default=str(_repo_root() / "artifacts" / "profile"))
    p.add_argument("--cache", default=str(_repo_root() / "artifacts" / "cache"))
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--device", default=None)
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("calibrate", help="refit I.4 calibrators (part of train)")
    p.set_defaults(func=lambda a: cmd_train(a))

    p = sub.add_parser("evaluate", help="locked-test evaluation report")
    p.add_argument("--bundle", default=str(_repo_root() / "artifacts" / "profile"))
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("bundle", help="bundle operations")
    bundle_sub = p.add_subparsers(dest="bundle_command", required=True)
    bv = bundle_sub.add_parser("verify")
    bv.add_argument("--bundle", default=str(_repo_root() / "artifacts" / "profile"))
    bv.set_defaults(func=cmd_bundle_verify)

    p = sub.add_parser("serve", help="run the offline console API")
    p.add_argument("--config", default="configs/core.yaml")
    p.add_argument("--port", type=int, default=None)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("replay", help="sealed replay operations")
    replay_sub = p.add_subparsers(dest="replay_command", required=True)
    rp = replay_sub.add_parser("predict")
    rp.add_argument("--episode", required=True, help="campaign:index")
    rp.add_argument("--bundle", default=str(_repo_root() / "artifacts" / "profile"))
    rp.add_argument("--cutoff", type=int, default=None)
    rp.set_defaults(func=cmd_replay_predict)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
