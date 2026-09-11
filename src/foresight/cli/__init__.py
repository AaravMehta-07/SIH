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
    import shutil
    import torch

    checks = []
    ok = True

    py_ok = sys.version_info[:2] == (3, 10)
    checks.append({"check": "python", "ok": py_ok, "detail": sys.version.split()[0]})
    ok = ok and py_ok

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

    parser_worker = _repo_root() / "src" / "foresight" / "ingest" / "pcap_worker.py"
    parser_ok = parser_worker.is_file()
    checks.append({"check": "pcap_parser_worker", "ok": parser_ok, "detail": str(parser_worker)})
    ok = ok and parser_ok
    free = shutil.disk_usage(_repo_root()).free
    disk_ok = free >= 2 * 1024**3
    checks.append({
        "check": "disk_budget",
        "ok": disk_ok,
        "detail": f"{free / 1024**3:.1f} GiB free (2 GiB minimum)",
    })
    ok = ok and disk_ok

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
        if not bundle.trained:
            ok = False
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
        "--members", args.members,
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


def cmd_data_qualify(args) -> int:
    """L.4 data qualify: verify a dataset registry (Section 6) — every
    registered object exists with the recorded size and SHA-256."""
    import hashlib

    manifest = Path(args.manifest)
    if not manifest.is_file():
        print(f"FAIL: manifest not found: {manifest}")
        return EXIT_INVALID_INPUT
    registry = json.loads(manifest.read_text(encoding="utf-8"))
    files = registry.get("files", [])
    if not files:
        print(f"FAIL: registry lists no files: {manifest}")
        return EXIT_INVALID_INPUT
    ok = True
    for entry in files:
        path = _repo_root() / entry["local_artifact"]
        name = Path(entry["local_artifact"]).name
        if not path.is_file():
            print(f"[FAIL] {name}: missing ({path})")
            ok = False
            continue
        if path.stat().st_size != int(entry["size_bytes"]):
            print(
                f"[FAIL] {name}: size mismatch "
                f"({path.stat().st_size} != {entry['size_bytes']})"
            )
            ok = False
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            print(f"[FAIL] {name}: SHA-256 mismatch")
            ok = False
            continue
        print(f"[OK ] {name}: {entry['size_bytes']} bytes verified")
    if ok:
        print(f"qualified: {registry.get('dataset_id', manifest.name)}")
        return 0
    return EXIT_FAILED_GATE


def cmd_replay_verify(args) -> int:
    """L.4 replay verify: check a forecast receipt against the immutable
    store — the committed record's canonical hash and its publication
    receipt (E.2/E.3)."""
    from foresight.storage.store import Storage

    receipt_path = Path(args.receipt)
    if not receipt_path.is_file():
        print(f"FAIL: receipt not found: {receipt_path}")
        return EXIT_INVALID_INPUT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    forecast_id = receipt.get("forecast_id") or receipt.get("id")
    if not forecast_id:
        print("FAIL: receipt carries no forecast_id")
        return EXIT_INVALID_INPUT
    store_root = Path(args.store)
    if not store_root.is_dir():
        print(f"FAIL: store not found: {store_root}")
        return EXIT_INVALID_INPUT
    storage = Storage(store_root)
    try:
        record = storage.get_forecast(forecast_id)
        if record is None:
            print(f"FAIL: forecast {forecast_id} is not committed in {store_root}")
            return EXIT_FAILED_GATE
        if not storage.verify_forecast(record):
            print(f"FAIL: forecast {forecast_id} fails canonical verification")
            return EXIT_FAILED_GATE
        claimed = receipt.get("forecast_hash")
        if claimed and claimed != record.get("forecast_hash"):
            print(
                f"FAIL: receipt hash {claimed[:16]}... does not match the "
                f"committed {str(record.get('forecast_hash'))[:16]}..."
            )
            return EXIT_FAILED_GATE
        published_at = storage.publication_receipt(forecast_id)
        if published_at is None:
            print(f"FAIL: forecast {forecast_id} was never published")
            return EXIT_FAILED_GATE
        print(
            f"OK: forecast {forecast_id} verified — canonical bytes intact, "
            f"published at {published_at}"
        )
        return 0
    finally:
        storage.close()


def cmd_release_verify(args) -> int:
    """L.4 release verify: every bundle named in a release manifest loads
    with verified hashes and carries an evaluation report."""
    from foresight.api.bundle import ArtifactError, load_bundle

    manifest = Path(args.manifest)
    if not manifest.is_file():
        print(f"FAIL: release manifest not found: {manifest}")
        return EXIT_INVALID_INPUT
    release = json.loads(manifest.read_text(encoding="utf-8"))
    bundles = release.get("bundles", [])
    if not bundles:
        print(f"FAIL: release manifest lists no bundles")
        return EXIT_INVALID_INPUT
    ok = True
    for entry in bundles:
        root = _repo_root() / entry["path"]
        label = entry.get("label", entry["path"])
        if not root.is_dir() and entry.get("optional"):
            print(f"[SKIP] {label}: not built (optional bundle)")
            continue
        try:
            bundle = load_bundle(root)
        except ArtifactError as exc:
            print(f"[FAIL] {label}: {exc}")
            ok = False
            continue
        report = root / "evaluation_report.json"
        report_ok = report.is_file()
        hashes = json.loads(
            (root / "artifact_hashes.json").read_text(encoding="utf-8")
        ) if (root / "artifact_hashes.json").is_file() else {}
        report_hash_ok = report_ok and (
            hashes.get("evaluation_report.json") is None
            or hashlib_sha256(report) == hashes["evaluation_report.json"]
        )
        status = "trained" if bundle.trained else "UNTRAINED fallback"
        if not report_ok or not report_hash_ok:
            print(
                f"[FAIL] {label}: bundle {status} but evaluation report "
                "missing or hash-inconsistent"
            )
            ok = False
            continue
        print(
            f"[OK ] {label}: {status}, {len(bundle.engines)} members, "
            "hashes verified, evaluation report consistent"
        )
    return 0 if ok else EXIT_FAILED_GATE


def hashlib_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="foresight", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="check dependencies and artifacts")
    p.add_argument("--config", default="configs/core.yaml")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("train", help="Section-35 training run")
    p.add_argument("--out", default=str(_repo_root() / "artifacts" / "profile"))
    p.add_argument("--cache", default=str(_repo_root() / "artifacts" / "cache"))
    p.add_argument(
        "--members",
        default="reference:0,1,2 gate:0,1 wide:0",
        help="heterogeneous member plan",
    )
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--device", default=None)
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("calibrate", help="refit I.4 calibrators (part of train)")
    p.add_argument("--out", default=str(_repo_root() / "artifacts" / "profile"))
    p.add_argument("--cache", default=str(_repo_root() / "artifacts" / "cache"))
    p.add_argument("--members", default="reference:0,1,2 gate:0,1 wide:0")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--device", default=None)
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("evaluate", help="locked-test evaluation report")
    p.add_argument("--bundle", default=str(_repo_root() / "artifacts" / "profile"))
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("bundle", help="bundle operations")
    bundle_sub = p.add_subparsers(dest="bundle_command", required=True)
    bv = bundle_sub.add_parser("verify")
    bv.add_argument("--bundle", default=str(_repo_root() / "artifacts" / "profile"))
    bv.set_defaults(func=cmd_bundle_verify)

    p = sub.add_parser("data", help="dataset qualification operations")
    data_sub = p.add_subparsers(dest="data_command", required=True)
    dq = data_sub.add_parser(
        "qualify", help="verify a dataset registry (Section 6)"
    )
    dq.add_argument("--manifest", required=True, help="dataset registry JSON")
    dq.set_defaults(func=cmd_data_qualify)

    p = sub.add_parser("release", help="release verification")
    release_sub = p.add_subparsers(dest="release_command", required=True)
    rv = release_sub.add_parser(
        "verify", help="verify every bundle in a release manifest"
    )
    rv.add_argument("--manifest", required=True, help="release manifest JSON")
    rv.set_defaults(func=cmd_release_verify)

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
    rv2 = replay_sub.add_parser(
        "verify", help="verify a forecast receipt against the store (E.2/E.3)"
    )
    rv2.add_argument("--receipt", required=True, help="receipt JSON path")
    rv2.add_argument(
        "--store", default=str(_repo_root() / "artifacts" / "runtime-store")
    )
    rv2.set_defaults(func=cmd_replay_verify)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
