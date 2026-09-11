"""Real-scenario end-to-end walkthrough (Build Spec Section 30 demo flow).

Drives the LIVE console API with the REAL trained bundle — no mocks, no
fixtures — through the complete analyst workflow:

    session -> capability -> forecast (sealed, provenance verified)
    -> evidence -> evidence queries (typed states) -> range action
    (policy -> authorize -> paired trial) -> replay reveal
    (predicted vs actual) -> evaluation -> receipt verification.

Run against a serving instance:

    python scripts/e2e_real_scenario.py [--base http://127.0.0.1:8001]

Exit 0 only if every step passes with real data.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASSED.append(name)
        print(f"  [OK ] {name}" + (f" - {detail}" if detail else ""))
    else:
        FAILED.append(name)
        print(f"  [FAIL] {name}" + (f" - {detail}" if detail else ""))


def api(base: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{path} -> HTTP {exc.code}: {exc.read().decode()[:300]}") from None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8001")
    parser.add_argument("--catalog-id", default=None)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print("== 1. health / catalog / tasks ==")
    health = api(base, "/health")
    check("service alive", health["status"] == "alive")
    check(
        "trained profile serving",
        health["trained"] is True,
        health["weights_profile"][:80],
    )
    tier_b = health.get("tier_b", {})
    check("tier B map disclosed", "paths" in tier_b and "queries" in tier_b)
    catalog = api(base, "/v1/catalog")
    entries = catalog["catalog"]
    check("catalog non-empty", len(entries) > 0, f"{len(entries)} entries")
    tasks = api(base, "/v1/tasks")
    check(
        "five-target ontology",
        len(tasks["tasks"]) == 5 and tasks["tasks"][0]["label_tier"] == "weak_proxy",
    )

    catalog_id = args.catalog_id or next(
        (
            e["catalog_id"]
            for e in entries
            if "web" in e.get("campaign", "") and e.get("synthetic", True)
        ),
        entries[0]["catalog_id"],
    )
    print(f"\n== 2. session ({catalog_id}) ==")
    session = api(base, "/v1/sessions", {"catalog_id": catalog_id})
    sid = session["session_id"]
    check("session created", bool(sid), sid)
    detail = api(base, f"/v1/sessions/{sid}")
    check(
        "capability report present",
        "capabilities" in detail and "capability_report" in detail,
    )
    check(
        "observation interval disclosed",
        len(detail.get("valid_cutoffs", [])) > 0,
        f"{len(detail.get('valid_cutoffs', []))} cutoffs",
    )

    print("\n== 3. sealed forecast with provenance ==")
    cutoffs = detail["valid_cutoffs"]
    cutoff = cutoffs[len(cutoffs) // 2 + 1]
    forecast = api(base, f"/v1/sessions/{sid}/forecast", {"cutoff_window": cutoff})
    check("forecast returned", forecast["cutoff_window"] == cutoff)
    record = forecast["record"]
    check("forecast committed + published", record["committed"] and record["published_at_ns"])
    provenance = record.get("provenance", {})
    check(
        "provenance sealed (T.4)",
        len(provenance.get("legal_prefix_hash", "")) == 64
        and len(provenance.get("source_object_hashes", {}).get("capture", "")) == 64,
    )
    check(
        "artifact hashes cited",
        bool(provenance.get("artifact_hashes", {}).get("models")),
    )
    # D.7 invariants on every supported task
    monotone = True
    supported = 0
    for entity in forecast["entities"]:
        for task in entity["tasks"]:
            if task["cumulative_risk"] is None:
                if task["status"] == "supported":
                    monotone = False
                continue
            supported += 1
            cum = task["cumulative_risk"]
            if any(b < a - 1e-9 for a, b in zip(cum, cum[1:])):
                monotone = False
    check("cumulative risk monotone + supported tasks present", monotone and supported > 0,
          f"{supported} supported task forecasts")

    print("\n== 4. evidence (deletion-tested attribution) ==")
    target = next(
        (e["name"] for e in forecast["entities"]
         if any(t["task_index"] == 2 and t["occurrence_probability"]
                for t in e["tasks"])),
        forecast["entities"][0]["name"],
    )
    evidence = api(
        base, f"/v1/sessions/{sid}/evidence",
        {"entity": target, "task_index": 2, "cutoff_window": cutoff},
    )
    check("attribution returned", evidence["entity"] == target)
    check(
        "fidelity measured",
        evidence.get("comprehensiveness") is not None
        and evidence.get("random_baseline_comprehensiveness") is not None,
    )
    check(
        "evidence flows on the legal prefix",
        len(evidence.get("flows", [])) > 0
        and all(0 <= f["window"] < 110 for f in evidence["flows"]),
    )

    print("\n== 5. evidence queries (Section 21) ==")
    proposals = api(base, "/v1/queries", {"session_id": sid, "cutoff_window": cutoff})
    check("query policy disclosed", "uncertain_rule" in proposals["policy"])
    check(
        "identity modality parsed",
        proposals["identity_quality"]["parsed_rows"] > 0,
        f"{proposals['identity_quality']['parsed_rows']} rows",
    )
    answered = 0
    for prop in proposals["proposals"]:
        answer = api(
            base,
            f"/v1/queries/{prop['proposal_id']}/execute",
            {"session_id": sid, "cutoff_window": cutoff},
        )
        if answer["status"] == "answered":
            answered += 1
            check(
                f"query answered for {prop['entity']}",
                len(answer["records"]) > 0,
                f"{len(answer['records'])} session records",
            )
        else:
            check(
                f"query typed state: {answer['status']} for {prop['entity']}",
                answer["status"] in ("unavailable", "denied", "expired"),
            )
        break  # one full execution is enough for the walkthrough
    print(f"  ({len(proposals['proposals'])} proposals at this cutoff)")

    print("\n== 6. range action (Sections 22-23) ==")
    externals = forecast["graph"].get("external_edges", [])
    pair = next(
        (
            (e["source"], e["target"])
            for e in externals
            if e["source"].endswith(".local") != e["target"].endswith(".local")
            and "c2" in (e["source"] + e["target"]).lower()
        ),
        None,
    ) or next(
        (
            (e["source"], e["target"])
            for e in externals
            if e["source"].endswith(".local") != e["target"].endswith(".local")
        ),
        (None, None),
    )
    check("cross-boundary pair observable", pair[0] is not None, f"{pair[0]} <-> {pair[1]}")
    if pair[0]:
        proposal = api(
            base, "/v1/actions/propose",
            {
                "session_id": sid, "cutoff_window": cutoff,
                "source": pair[0], "target": pair[1],
            },
        )
        check(
            "policy check passed",
            proposal.get("authorizable") is True
            and proposal["evidence_binding"]["forecast_hash"],
        )
        auth = api(base, f"/v1/actions/{proposal['action_id']}/authorize", {})
        check("authorization recorded", auth["status"] == "authorized")
        trial = api(
            base, f"/v1/actions/{proposal['action_id']}/execute", {"dry_run": True}
        )
        outcome = trial.get("trial", {})
        check(
            "paired trial executed with postcondition",
            trial["status"] in ("succeeded", "failed")
            and "no_action" in outcome
            and "action_arm" in outcome,
            f"averted={len(outcome.get('averted_events', []))}, "
            f"blocked={outcome.get('action_arm', {}).get('packets_blocked', 0)}",
        )
        check(
            "benign disruption measured",
            "benign_packet_loss_pct" in outcome.get("service_disruption", {}),
        )

    print("\n== 7. reveal (predicted vs actual) ==")
    reveal = api(base, f"/v1/sessions/{sid}/reveal", {"cutoff_window": cutoff})
    check("ground truth revealed", len(reveal["events"]) > 0)
    comparison = reveal.get("forecast_comparison")
    check(
        "alert outcomes scored",
        comparison is not None and all(
            c["outcome"] in (
                "correct_warning", "false_alert", "early_warning_outside_horizon"
            )
            for c in comparison
        ),
        f"{len(comparison or [])} scored alerts",
    )

    print("\n== 8. evaluation report ==")
    evaluation = api(base, "/v1/evaluation")
    check(
        "locked-test report present",
        evaluation.get("locked_test_report") is not None,
    )
    if evaluation.get("locked_test_report"):
        gates = evaluation["locked_test_report"]["gates"]
        check(
            "gates honestly reported",
            all(g["status"] in ("pass", "fail", "inconclusive") for g in gates),
            ", ".join(f"{g['name']}={g['status']}" for g in gates[:4]),
        )

    print("\n== 9. receipt verification (E.2/E.3) ==")
    with tempfile.TemporaryDirectory() as td:
        receipt = Path(td) / "receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "forecast_id": record["forecast_id"],
                    "forecast_hash": record["forecast_hash"],
                }
            ),
            encoding="utf-8",
        )
        from foresight.cli import cmd_replay_verify

        code = cmd_replay_verify(
            type("Args", (), {"receipt": str(receipt),
                              "store": str(REPO_ROOT / "artifacts" / "runtime-store")})()
        )
        check("receipt verifies against the store", code == 0)

    print(f"\n{'=' * 60}")
    print(f"REAL-SCENARIO E2E: {len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        for f in FAILED:
            print("  FAILED:", f)
        return 1
    print("ALL REAL-SCENARIO CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
