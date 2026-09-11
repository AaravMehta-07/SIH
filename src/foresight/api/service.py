"""Session service over real synthetic episodes (Build Spec K.2, L.2).

Each session wraps one synthetic capture episode through the REAL pipeline:
packet telemetry -> eligible prefix windows -> scaled GraphWindowBatch ->
I.5 ensemble forecast with I.4 calibration -> committed ForecastRecord
(E.2/E.3) -> SENTINEL novelty -> deletion-tested evidence on demand.

Honesty contract: the forecast path never reads episode ground truth; only
``reveal`` returns it (K.2, SE02). Rule-based flags are observed-evidence
annotations on legal features, labeled detection-style, never forecasts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ..contracts.quality import NOT_SUPPORTED_WIRE
from ..data.clips import (
    HISTORY_WINDOWS,
    build_serving_windows,
    precompute_episode,
    sample_cutoffs,
)
from ..data.episodes import Episode, build_episode, is_internal
from ..explain.attribution import AttributionBudget, explain_target
from ..explain.paths import rank_candidate_edges
from ..features.registry import GLOBAL_FEATURE_NAMES, NODE_FEATURE_NAMES
from ..graphs.collate import collate_windows
from ..ingest.identity import (
    IdentityAdapter,
    generate_identity_log,
    identity_log_csv,
)
from ..labels.ontology import SIH_TACTICS, TASK_DEFINITIONS
from ..labels.targets import all_pair_candidates
from ..models.survival import conditional_eta
from ..paths.candidates import build_candidate_set
from ..queries import QueryEngine
from ..runtime.forecast import ForecastRequest
from ..sentinel.reference import window_to_device
from ..sentinel.scorer import SentinelScorer, collect_matured_residuals
from ..storage.store import Storage
from .bundle import RuntimeBundle

_NS = 1_000_000_000
WINDOW_NS = 30 * _NS
HORIZON_BINS = 60

#: Curated demo catalog: one episode per family with analyst-facing titles.
CATALOG: tuple[dict, ...] = (
    {
        "campaign": "benign-baseline",
        "index": 3,
        "title": "Benign corporate baseline",
        "summary": (
            "Ordinary business traffic — browsing, service calls, monitoring "
            "and one nightly backup. No attack events; the honest outcome is "
            "a quiet forecast and zero alerts."
        ),
    },
    {
        "campaign": "benign-drift",
        "index": 1,
        "title": "Benign drift day (patch rollout)",
        "summary": (
            "A patch push and an off-schedule backup raise volumes above "
            "baseline without any attack. Exercises SENTINEL false-novelty "
            "behavior: benign change is change detection, never an alert."
        ),
    },
    {
        "campaign": "web-to-lateral",
        "index": 0,
        "title": "Web compromise to lateral movement",
        "summary": (
            "An external exploit hits the DMZ web server; C2 beaconing and an "
            "internal port scan follow, then two lateral-movement hops reach "
            "the app tier and the database."
        ),
    },
    {
        "campaign": "c2-exfil",
        "index": 0,
        "title": "Established C2 with staged exfiltration",
        "summary": (
            "A compromised workstation beacons quietly, moves laterally to "
            "the file server, stages archives in the database and then "
            "exfiltrates them in bulk."
        ),
    },
    {
        "campaign": "slow-recon",
        "index": 0,
        "title": "Low-and-slow reconnaissance",
        "summary": (
            "A 2-port-per-second scan stretched over fifteen minutes with a "
            "quiet beacon — the hard case where rate-based detectors stay "
            "silent."
        ),
    },
    {
        "campaign": "cred-spray",
        "index": 0,
        "title": "Credential spray against the DC",
        "summary": (
            "Forty-four short SMB attempts against the domain controller, "
            "mostly denied, followed by a lateral hop to the file server."
        ),
    },
)


@dataclass
class EpisodeSession:
    session_id: str
    episode: Episode
    bundle: RuntimeBundle
    storage: Storage
    precomputed: object = None
    created_at: float = 0.0
    forecast_cache: dict[int, dict] = None
    record_ids: dict[int, str] = None
    query_engine: QueryEngine = None
    identity_quality: dict = None

    def __post_init__(self) -> None:
        if self.precomputed is None:
            self.precomputed = precompute_episode(self.episode)
        if self.forecast_cache is None:
            self.forecast_cache = {}
        if self.record_ids is None:
            self.record_ids = {}
        if not self.created_at:
            self.created_at = time.time()
        # Tier B identity modality: a separate replay-only telemetry stream
        # (Section 21). Generated deterministically, parsed by the real
        # adapter boundary, never read by the forecasting pipeline.
        if self.query_engine is None:
            records = generate_identity_log(self.episode)
            parsed = IdentityAdapter().parse(identity_log_csv(records))
            self.identity_quality = parsed.quality_report
            self.query_engine = QueryEngine(parsed.records)

    @property
    def identity_log_csv_text(self) -> str:
        return identity_log_csv(generate_identity_log(self.episode))

    # ------------------------------------------------------------------
    @property
    def entity_ids(self) -> tuple[str, ...]:
        return self.precomputed.entity_ids

    def valid_cutoffs(self) -> list[int]:
        return sample_cutoffs(self.episode)

    def _example(self, cutoff_window: int):
        """Serving inputs: windows + frozen candidates, never the training
        target object (C.2)."""

        class _ServingInputs:
            pass

        inputs = _ServingInputs()
        inputs.windows, inputs.candidate_pairs = build_serving_windows(
            self.precomputed, self.bundle.scaler, cutoff_window
        )
        inputs.entity_ids = self.precomputed.entity_ids
        return inputs

    def run_forecast(self, cutoff_window: int) -> dict:
        """Full Section-26 forecast at a cutoff; committed and published."""
        if cutoff_window not in self.valid_cutoffs():
            raise ValueError(
                f"cutoff_window must be one of {self.valid_cutoffs()}"
            )
        cached = self.forecast_cache.get(cutoff_window)
        if cached is not None:
            return cached

        example = self._example(cutoff_window)
        windows = example.windows
        request = ForecastRequest(
            horizon_bins=HORIZON_BINS,
            bin_seconds=30,
            task_mask=torch.ones(5, dtype=torch.bool),
            min_occurrence_probability=0.30,
            published_horizons_seconds=(300, 900, 1800),
            candidate_pairs=example.candidate_pairs,
        )
        start = time.perf_counter()
        result = self.bundle.ensemble.forecast(windows, request)
        compute_seconds = time.perf_counter() - start

        payload = self._forecast_payload(
            example, result, cutoff_window, compute_seconds
        )

        # Commit the immutable record, then publish (E.2/E.3).
        record = {
            "id": f"fc-{uuid.uuid4().hex[:16]}",
            "schema": "foresight.core.2026-09",
            "tenant_id": "local",
            "session_id": self.session_id,
            "scope_id": f"scope-{self.episode.episode_id}",
            "decision_cutoff_ns": str(cutoff_window * WINDOW_NS),
            "session_cutoff_window": cutoff_window,
            "model": payload["model"],
            "targets": [
                {
                    "entity_id": e["name"],
                    "task_index": t["task_index"],
                    "status": t["status"],
                    "bin_seconds": 30,
                    "cumulative_risk": t["cumulative_risk"],
                    "no_event_mass": t["no_event_mass"],
                    "conditional_eta": t["eta"],
                    "trust": t["trust"],
                }
                for e in payload["entities"]
                for t in e["tasks"]
            ],
            "runtime_health": payload["coverage"]["health"],
            "synthetic": True,
        }
        forecast_hash = self.storage.commit_forecast(record)
        published_at = self.storage.publish_forecast(record["id"])
        payload["record"] = {
            "forecast_id": record["id"],
            "forecast_hash": forecast_hash,
            "committed": True,
            "published_at_ns": str(published_at),
            "compute_to_ledger_seconds": round(compute_seconds, 3),
        }
        self.record_ids[cutoff_window] = record["id"]
        self.forecast_cache[cutoff_window] = payload
        return payload

    def _forecast_payload(
        self, example, result, cutoff_window: int, compute_seconds: float
    ) -> dict:
        from ..runtime.forecast import DEFAULT_DISPLAY_ETA_THRESHOLD

        disagreement = result.model_disagreement or {}
        entities = []
        for entity in result.entities:
            name = example.entity_ids[entity.slot]
            role = self._role(name)
            tactic_probs = torch.sigmoid(
                result.tactic_logits[result.horizon_bins - 1, entity.slot].to(
                    torch.float64
                )
            )
            tasks = []
            for tf in entity.task_forecasts:
                task = TASK_DEFINITIONS[tf.task_index]
                threshold = self.bundle.policy_threshold(tf.task_index)
                occurrence = (
                    float(tf.distribution.cumulative_risk[-1])
                    if tf.distribution is not None
                    else None
                )
                alerting = (
                    threshold is not None
                    and tf.distribution is not None
                    and float(tf.distribution.cumulative_risk[9]) > threshold
                )
                tasks.append(
                    {
                        "task_index": tf.task_index,
                        "task_id": task.id,
                        "task_label": task.label,
                        "label_tier": task.label_tier,
                        "status": tf.status,
                        "calibration_status": tf.calibration_status,
                        "cumulative_risk": (
                            [round(float(v), 6) for v in tf.distribution.cumulative_risk]
                            if tf.distribution is not None
                            else None
                        ),
                        "event_mass": (
                            [round(float(v), 6) for v in tf.distribution.event_mass]
                            if tf.distribution is not None
                            else None
                        ),
                        "no_event_mass": (
                            round(float(tf.distribution.no_event_mass), 6)
                            if tf.distribution is not None
                            else None
                        ),
                        "occurrence_probability": (
                            round(occurrence, 6) if occurrence is not None else None
                        ),
                        "eta": (
                            {
                                "median_bin": tf.conditional_eta.median_bin,
                                "median_seconds": tf.conditional_eta.median_seconds,
                                "occurrence_probability": round(
                                    tf.conditional_eta.occurrence_probability, 6
                                ),
                                "bin_seconds": tf.conditional_eta.bin_seconds,
                                "condition": (
                                    "median given occurrence within the "
                                    "supported horizon"
                                ),
                            }
                            if tf.conditional_eta is not None
                            else None
                        ),
                        "eta_withheld_reason": tf.eta_withheld_reason,
                        "disagreement": (
                            round(disagreement[(entity.slot, tf.task_index)], 6)
                            if (entity.slot, tf.task_index) in disagreement
                            else None
                        ),
                        "policy_threshold": threshold,
                        "alerting": bool(alerting),
                        "trust": {
                            "status": "supported" if tf.status == "supported" else NOT_SUPPORTED_WIRE,
                            "calibration": tf.calibration_status,
                        },
                    }
                )
            entities.append(
                {
                    "slot": entity.slot,
                    "name": name,
                    "role": role,
                    "tasks": tasks,
                    "tactic_tags": [
                        {"tactic": SIH_TACTICS[i], "probability": round(float(p), 4)}
                        for i, p in enumerate(tactic_probs)
                    ],
                }
            )

        graph = self._graph_payload(example, cutoff_window)
        novelty = self._novelty_payload(example, cutoff_window)
        flags = self._flagged_evidence(cutoff_window)
        paths_payload = self._paths_payload(example, result, cutoff_window)

        return {
            "weights_profile": self.bundle.weights_profile,
            "model": {
                "kind": "ensemble",
                "members": len(self.bundle.engines),
                "variants": [v for v, _s in self.bundle.members],
                "seeds": list(self.bundle.seeds),
                "params_per_member": self.bundle.params_per_member,
                "trained": self.bundle.trained,
            },
            "horizon_bins": result.horizon_bins,
            "bin_seconds": result.bin_seconds,
            "published_horizons_seconds": list(result.published_horizons_seconds),
            "cutoff_window": cutoff_window,
            "cutoff_seconds": cutoff_window * 30,
            "compute_seconds": round(compute_seconds, 3),
            "display_eta_threshold": DEFAULT_DISPLAY_ETA_THRESHOLD,
            "entities": entities,
            "graph": graph,
            "novelty": novelty,
            "flagged": flags,
            "coverage": {
                "history_windows": HISTORY_WINDOWS,
                "window_count": HISTORY_WINDOWS,
                "health": "healthy",
                "sensor_gaps": [
                    {"host": h, "from_window": f // 30 + 1, "to_window": t // 30 + 1}
                    for h, f, t in self.episode.capture.sensor_gaps
                ],
                "observed_hosts": len(self.entity_ids),
            },
            "paths": paths_payload,
        }

    def _paths_payload(self, example, result, cutoff_window: int) -> dict:
        """Tier A candidate-edge projection + Tier B typed-event paths.

        The two are never merged: marginal future-communication probabilities
        (edge head) stay separate from the next-mark decoder's autoregressive
        path products (Section 20)."""
        payload = {
            "status": "not_supported",
            "note": (
                "Tier B typed-event path search has no trained bundle; "
                "candidate edges are marginal future-communication "
                "probabilities, not a calibrated attack path (Section 20)"
            ),
            "candidate_edges": (
                rank_candidate_edges(
                    result.edge_logits,
                    example.candidate_pairs,
                    example.entity_ids,
                    horizon_bins=result.horizon_bins,
                ).to_json()["edges"]
                if result.edge_logits is not None
                else []
            ),
        }
        engine = self.bundle.path_engine
        if engine is None:
            return payload
        with torch.no_grad():
            model = self.bundle.engines[0].model
            device = next(model.parameters()).device
            state = model.observe_clip(
                [window_to_device(w, device) for w in example.windows]
            )
        forecast = engine.forecast(
            self.episode,
            state.entity_memory,
            state.global_context,
            cutoff_window,
        )
        payload.update(forecast.to_json())
        payload["weights_profile"] = engine.weights_profile
        return payload

    def _role(self, entity_name: str) -> str:
        for host in self.episode.capture.hosts:
            if host.name == entity_name:
                return host.role
        return "external"

    # ------------------------------------------------------------------
    def _graph_payload(self, example, cutoff_window: int) -> dict:
        """Graph layout + observed (prefix) edges + predicted edges."""
        import math

        roles: list[str] = []
        for name in example.entity_ids:
            role = self._role(name)
            if role not in roles:
                roles.append(role)
        sector = 2 * math.pi / max(len(roles), 1)
        nodes = []
        by_role: dict[str, list[int]] = {r: [] for r in roles}
        for slot, name in enumerate(example.entity_ids):
            by_role[self._role(name)].append(slot)
        for role, slots in by_role.items():
            r = sector * (roles.index(role) + 0.5)
            for i, slot in enumerate(slots):
                spread = (
                    (i - (len(slots) - 1) / 2)
                    * sector / max(len(slots) + 1, 2)
                )
                angle = r + spread
                nodes.append(
                    {
                        "slot": slot,
                        "name": example.entity_ids[slot],
                        "role": role,
                        "x": round(50 + 42 * math.cos(angle), 2),
                        "y": round(50 + 42 * math.sin(angle), 2),
                    }
                )
        nodes.sort(key=lambda n: n["slot"])

        # Observed edges with per-window activity over the prefix (EX02:
        # every edge maps to legal-prefix packet rows).
        prefix = self.precomputed.prefix_windows[cutoff_window]
        edge_windows: dict[tuple[int, int], list[int]] = {}
        for w_index, window in enumerate(prefix):
            for e in range(window.edge_index.shape[1]):
                u = int(window.edge_index[0, e])
                v = int(window.edge_index[1, e])
                edge_windows.setdefault((u, v), []).append(w_index)
        observed = [
            {
                "source": example.entity_ids[u],
                "target": example.entity_ids[v],
                "windows": ws,
                "first_window": cutoff_window - HISTORY_WINDOWS + ws[0],
                "last_window": cutoff_window - HISTORY_WINDOWS + ws[-1],
            }
            for (u, v), ws in sorted(edge_windows.items())
        ]
        external_edges = self._observed_external_pairs(cutoff_window)
        return {"nodes": nodes, "observed_edges": observed, "external_edges": external_edges}

    def _observed_external_pairs(self, cutoff_window: int) -> list[dict]:
        """Directed internal<->external pairs on the eligible prefix (the
        block_edge scope allowlist draws from these; graph edges are
        internal-only by G.2)."""
        import numpy as np

        cutoff_ns = cutoff_window * WINDOW_NS
        table = self.episode.capture.packets
        names = [h.name for h in self.episode.capture.hosts]
        mask = (
            (table["t_ns"] <= cutoff_ns)
            & (table["available_ns"] <= cutoff_ns)
            & (table["ingested_ns"] <= cutoff_ns)
        )
        rows = np.where(mask)[0]
        counts: dict[tuple[str, str], dict] = {}
        for r in rows:
            s = names[int(table["src"][r])]
            d = names[int(table["dst"][r])]
            s_int, d_int = is_internal(s), is_internal(d)
            if s_int == d_int:
                continue  # only cross-boundary pairs matter here
            key = (s, d)
            entry = counts.setdefault(key, {"packets": 0, "last_window": 0})
            entry["packets"] += 1
            entry["last_window"] = max(
                entry["last_window"], int(table["t_ns"][r]) // WINDOW_NS
            )
        return [
            {
                "source": s,
                "target": t,
                "packets": v["packets"],
                "last_window": v["last_window"],
            }
            for (s, t), v in sorted(counts.items())
        ]

    def _novelty_payload(self, example, cutoff_window: int) -> dict:
        """SENTINEL diagnostics from matured residuals + embeddings."""
        if self.bundle.novelty_reference is None:
            return {
                "status": "unavailable",
                "note": self.bundle.novelty_note,
            }
        scorer = SentinelScorer(self.bundle.novelty_reference)
        windows = example.windows
        engine = self.bundle.engines[0]
        device = next(engine.model.parameters()).device
        matured = collect_matured_residuals(
            engine.model,
            device,
            windows,
            entity_ids=example.entity_ids,
            latest_cutoff_window=cutoff_window,
        )
        # one observed state; slice each entity's memory row from it
        with torch.no_grad():
            state = engine.model.observe_clip(
                [window_to_device(w, device) for w in windows]
            )
        results = {}
        for slot, name in enumerate(example.entity_ids):
            diag = scorer.score(state.entity_memory[0, slot], matured, entity=name)
            results[name] = diag.to_json()
        overall = max(
            (
                d["residual_score"]
                for d in results.values()
                if d["residual_score"] is not None
            ),
            default=None,
        )
        return {
            "status": (
                "novel" if any(d["status"] == "novel" for d in results.values())
                else "reference_like"
                if results
                else "unavailable"
            ),
            "max_residual_score": overall,
            "per_entity": results,
            "note": (
                "unexpectedness vs the frozen benign reference; benign change "
                "also triggers this - not an attack probability"
            ),
        }

    def _flagged_evidence(self, cutoff_window: int) -> list[dict]:
        """Rule-based flags on legal prefix features (observed evidence,
        detection-style annotations — distinct from model forecasts)."""
        flags: list[dict] = []
        prefix = self.precomputed.prefix_windows[cutoff_window]
        table = self.episode.capture.packets
        for w_index, window in enumerate(prefix):
            abs_window = cutoff_window - HISTORY_WINDOWS + w_index
            rows = np.where(
                (table["t_ns"] > abs_window * WINDOW_NS)
                & (table["t_ns"] <= (abs_window + 1) * WINDOW_NS)
            )[0]
            for slot in range(len(self.entity_ids)):
                name = self.entity_ids[slot]
                nv = window.node_values[slot]
                valid = window.node_validity[slot]
                if (
                    valid[11]
                    and nv[11] > 0.9
                    and nv[10] > 20
                ):
                    flags.append(
                        {
                            "window": abs_window,
                            "kind": "host",
                            "entity": name,
                            "reason": (
                                f"port-scan signature: {int(nv[10])} distinct "
                                f"destination ports, entropy {nv[11]:.2f}"
                            ),
                        }
                    )
                elif valid[8] and nv[8] > 0.5 and nv[0] > 8:
                    flags.append(
                        {
                            "window": abs_window,
                            "kind": "host",
                            "entity": name,
                            "reason": (
                                f"{int(nv[0])} SYNs, {nv[8]*100:.0f}% failed "
                                "connection attempts (spray/scan pattern)"
                            ),
                        }
                    )
                elif (
                    valid[17]
                    and nv[17] > 40000
                ):
                    flags.append(
                        {
                            "window": abs_window,
                            "kind": "flow",
                            "entity": name,
                            "reason": (
                                f"bulk transfer: p95 segment {int(nv[17]):,} bytes"
                            ),
                        }
                    )
        # deduplicate by (entity, reason-kind) keeping the latest window
        dedup: dict[tuple, dict] = {}
        for f in flags:
            key = (f["entity"], f["reason"].split(":")[0])
            dedup[key] = f
        return sorted(dedup.values(), key=lambda f: f["window"])

    # ------------------------------------------------------------------
    def evidence(self, entity: str, task_index: int, cutoff_window: int) -> dict:
        """Deletion-tested attribution + source-linked packet evidence."""
        engine = self.bundle.engines[0]
        result = explain_target(
            engine,
            self.episode,
            self.precomputed,
            self.bundle.scaler,
            cutoff_window=cutoff_window,
            entity=entity,
            task_index=task_index,
            horizon_bins=10,
            budget=AttributionBudget(max_groups=12, random_controls=6, top_k_evidence=4),
        )
        # Resolve packet rows to readable flow summaries (EX02).
        table = self.episode.capture.packets
        hosts = self.episode.capture.hosts
        flows = []
        for item in result.evidence[:8]:
            sample_rows = item.packet_rows[:6]
            for row in sample_rows:
                r = table[row]
                flows.append(
                    {
                        "window": int(r["t_ns"]) // WINDOW_NS,
                        "source": hosts[int(r["src"])].name,
                        "target": hosts[int(r["dst"])].name,
                        "dport": int(r["dport"]),
                        "protocol": ("tcp", "udp", "other")[int(r["proto"])],
                        "bytes": int(r["wire_len"]),
                        "at_ns": str(int(r["t_ns"])),
                    }
                )
        payload = result.to_json()
        payload["flows"] = flows
        payload["weights_profile"] = self.bundle.weights_profile
        return payload

    def reveal(self, cutoff_window: int | None = None) -> dict:
        """Evaluator-side ground truth (K.2: only reveal returns it)."""
        cutoff = cutoff_window or max(self.valid_cutoffs())
        events = []
        for g in self.episode.ground_truth:
            events.append(
                {
                    "entity": g.entity,
                    "task_index": g.task_index,
                    "task_id": TASK_DEFINITIONS[g.task_index].id,
                    "task_label": TASK_DEFINITIONS[g.task_index].label,
                    "label_tier": g.label_tier,
                    "event_window": g.event_time_ns // WINDOW_NS + 1,
                    "relative_to_cutoff": (
                        g.event_time_ns // WINDOW_NS + 1 - cutoff
                    ),
                    "status": g.status,
                }
            )
        # Compare the committed forecast (if any) against this truth.
        comparison = None
        if cutoff in self.record_ids:
            payload = self.forecast_cache.get(cutoff)
            if payload:
                comparison = []
                for entity in payload["entities"]:
                    for task in entity["tasks"]:
                        if not task["alerting"]:
                            continue
                        event = next(
                            (
                                e
                                for e in events
                                if e["entity"] == entity["name"]
                                and e["task_index"] == task["task_index"]
                            ),
                            None,
                        )
                        if event and 0 < event["relative_to_cutoff"] <= 10:
                            outcome = "correct_warning"
                            lead = event["relative_to_cutoff"] * 30
                        elif event:
                            outcome = "early_warning_outside_horizon"
                            lead = None
                        else:
                            outcome = "false_alert"
                            lead = None
                        comparison.append(
                            {
                                "entity": entity["name"],
                                "task_index": task["task_index"],
                                "outcome": outcome,
                                "lead_seconds": lead,
                            }
                        )
        return {
            "cutoff_window": cutoff,
            "weights_profile": self.bundle.weights_profile,
            "note": (
                "Ground truth was withheld from the forecast endpoint; this "
                "reveal is the evaluation-side record (K.2 replay semantics)."
            ),
            "events": events,
            "forecast_comparison": comparison,
        }

    # ------------------------------------------------------------------
    def propose_queries(self, cutoff_window: int) -> dict:
        """Tier B evidence requests (Section 21): transparent-rule proposals
        from the committed forecast at this cutoff."""
        payload = self.forecast_cache.get(cutoff_window)
        if payload is None:
            raise ValueError("run the forecast at this cutoff first")
        proposals = self.query_engine.propose(payload, cutoff_window)
        return {
            "cutoff_window": cutoff_window,
            "policy": self.query_engine.status(),
            "identity_quality": self.identity_quality,
            "proposals": proposals,
            "note": (
                "default stretch policy (Section 21): a transparent rule, not "
                "a learned selector; waiting and acting immediately remain "
                "the comparison policies"
            ),
        }

    def execute_query(self, proposal_id: str, cutoff_window: int) -> dict:
        """Execute one allowlisted request; answers carry their own clocks
        and create a new forecast version (never rewrite the seal)."""
        if cutoff_window not in self.valid_cutoffs():
            raise ValueError(f"unknown cutoff_window {cutoff_window}")
        answer = self.query_engine.execute(
            proposal_id, cutoff_window * WINDOW_NS
        )
        answer["cutoff_window"] = cutoff_window
        answer["query_policy"] = self.query_engine.status()
        return answer
