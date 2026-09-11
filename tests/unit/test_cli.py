"""L.4 CLI command tests: data qualify, replay verify, release verify."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from foresight.cli import (  # noqa: E402
    EXIT_FAILED_GATE,
    EXIT_INVALID_INPUT,
    cmd_data_qualify,
    cmd_release_verify,
    cmd_replay_verify,
)
from foresight.storage.store import Storage  # noqa: E402


class _Args:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _write_registry(tmp_path: Path, file_bytes: bytes, sha256: str) -> Path:
    data = tmp_path / "raw.binetflow"
    data.write_bytes(file_bytes)
    registry = {
        "dataset_id": "test-ds",
        "files": [
            {
                "role": "train",
                "kind": "binetflow",
                "local_artifact": str(data),
                "size_bytes": len(file_bytes),
                "sha256": sha256,
            }
        ],
    }
    manifest = tmp_path / "registry.json"
    manifest.write_text(json.dumps(registry), encoding="utf-8")
    return manifest


def test_data_qualify_verifies_registered_objects(tmp_path, monkeypatch, capsys):
    payload = b"StartTime,Dur,Proto\n" + b"row" * 64
    import hashlib

    good = _write_registry(tmp_path, payload, hashlib.sha256(payload).hexdigest())
    monkeypatch.chdir(tmp_path)
    # local_artifact is absolute; the resolver joins the repo root, and
    # Path / absolute simply yields the absolute path.
    assert cmd_data_qualify(_Args(manifest=str(good))) == 0
    out = capsys.readouterr().out
    assert "verified" in out and "qualified" in out


def test_data_qualify_rejects_hash_mismatch(tmp_path, monkeypatch, capsys):
    payload = b"tamperable bytes"
    bad = _write_registry(
        tmp_path, payload, "0" * 64
    )
    monkeypatch.chdir(tmp_path)
    assert cmd_data_qualify(_Args(manifest=str(bad))) == EXIT_FAILED_GATE
    assert "SHA-256 mismatch" in capsys.readouterr().out


def test_data_qualify_missing_manifest_is_invalid_input(tmp_path):
    assert (
        cmd_data_qualify(_Args(manifest=str(tmp_path / "nope.json")))
        == EXIT_INVALID_INPUT
    )


def test_replay_verify_round_trip(tmp_path):
    """Commit + publish a forecast, then verify its receipt (E.2/E.3)."""
    store = Storage(tmp_path / "store")
    try:
        record = {
            "id": "fc-test0001",
            "schema": "foresight.core.2026-09",
            "tenant_id": "local",
            "session_id": "sess-1",
            "scope_id": "scope-1",
            "decision_cutoff_ns": "60000000000",
            "targets": [],
        }
        forecast_hash = store.commit_forecast(record)
        store.publish_forecast(record["id"])
    finally:
        store.close()
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps({"forecast_id": record["id"], "forecast_hash": forecast_hash}),
        encoding="utf-8",
    )
    assert (
        cmd_replay_verify(_Args(receipt=str(receipt), store=str(tmp_path / "store")))
        == 0
    )
    # a receipt claiming a different hash fails the gate
    tampered = tmp_path / "tampered.json"
    tampered.write_text(
        json.dumps({"forecast_id": record["id"], "forecast_hash": "f" * 64}),
        encoding="utf-8",
    )
    assert (
        cmd_replay_verify(_Args(receipt=str(tampered), store=str(tmp_path / "store")))
        == EXIT_FAILED_GATE
    )


def test_replay_verify_missing_receipt_is_invalid_input(tmp_path):
    assert (
        cmd_replay_verify(
            _Args(receipt=str(tmp_path / "nope.json"), store=str(tmp_path))
        )
        == EXIT_INVALID_INPUT
    )


def test_release_verify_skips_optional_unbuilt_bundles(tmp_path, capsys):
    manifest = tmp_path / "release.json"
    manifest.write_text(
        json.dumps(
            {
                "bundles": [
                    {"label": "absent", "path": "artifacts/does-not-exist",
                     "optional": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert cmd_release_verify(_Args(manifest=str(manifest))) == 0
    assert "SKIP" in capsys.readouterr().out
