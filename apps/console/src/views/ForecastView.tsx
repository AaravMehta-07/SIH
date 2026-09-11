// Analyst workspace (K.2): the operational core in one composition —
// risk-sorted entity list, the observed/predicted network, and a
// selected-entity inspection panel (risk trajectory, ETA, trust, SENTINEL,
// provenance, and the Section 22-23 intervene flow). The decision cutoff is
// the time axis of everything on screen.

import { useMemo, useState } from "react";
import type { ActionProposalPayload, ForecastPayload, SessionSummary, TrialPayload } from "../types";
import { TASKS } from "../types";
import { api } from "../api";
import {
  ErrorPanel,
  RiskTimeline,
  Skeleton,
  pct,
  riskLevel,
  taskAt,
  taskColor,
  useCountUp,
} from "../components/charts";
import { GraphView } from "../components/GraphView";

const HORIZONS = [
  { minutes: 5, bins: 10, label: "5 min" },
  { minutes: 15, bins: 30, label: "15 min" },
  { minutes: 30, bins: 60, label: "30 min" },
];

function riskColor(level: string): string {
  if (level === "l4" || level === "l3") return "var(--critical)";
  if (level === "l2") return "var(--serious)";
  if (level === "l1") return "var(--warning)";
  return "var(--ink-3)";
}

function occurrenceAt(entity: ForecastPayload["entities"][number], bins: number): number {
  let max = 0;
  for (const t of entity.tasks) {
    if (t.cumulative_risk) {
      max = Math.max(max, t.cumulative_risk[Math.min(bins, t.cumulative_risk.length) - 1]);
    }
  }
  return max;
}

/** One entity row: risk dot, identity, risk bar — no card, one line. */
function EntityRow({
  entity,
  selected,
  bins,
  onSelect,
}: {
  entity: ForecastPayload["entities"][number];
  selected: boolean;
  bins: number;
  onSelect: (name: string) => void;
}) {
  const risk = occurrenceAt(entity, bins);
  const level = riskLevel(risk);
  const alerting = entity.tasks.some((t) => t.alerting);
  const animated = useCountUp(risk);
  return (
    <button
      className={`entity-row ${selected ? "selected" : ""}`}
      onClick={() => onSelect(entity.name)}
      aria-current={selected ? "true" : undefined}
    >
      <span
        className="state-marker"
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: alerting ? "var(--critical)" : riskColor(level),
          boxShadow: alerting ? "0 0 7px rgba(208,59,59,.8)" : undefined,
        }}
        aria-hidden="true"
      />
      <span className="entity-id">
        <span className="entity-name">{entity.name.split(".")[0]}</span>
        <span className="entity-role">{entity.role}</span>
      </span>
      <span className="entity-risk">
        <span className="risk-pct" style={{ color: riskColor(level) }}>
          {(animated * 100).toFixed(1)}%
        </span>
        <span className="risk-track" aria-hidden="true">
          <span
            className="risk-fill"
            style={{ width: `${Math.max(risk * 100, 1.5)}%`, background: riskColor(level) }}
          />
        </span>
      </span>
    </button>
  );
}

/** The Section 22-23 intervene flow, progressively disclosed. */
function Intervene({ forecast, session }: { forecast: ForecastPayload; session: SessionSummary }) {
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [proposal, setProposal] = useState<ActionProposalPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pairs = useMemo(() => {
    const out: { internal: string; external: string; packets: number }[] = [];
    const seen = new Set<string>();
    for (const e of forecast.graph.external_edges ?? []) {
      const aIn = e.source.endsWith(".local");
      const bIn = e.target.endsWith(".local");
      if (aIn === bIn) continue;
      const internal = aIn ? e.source : e.target;
      const external = aIn ? e.target : e.source;
      if (!seen.has(internal + external)) {
        seen.add(internal + external);
        out.push({ internal, external, packets: e.packets });
      }
    }
    return out.sort((a, b) => b.packets - a.packets);
  }, [forecast]);

  const cutoff = forecast.cutoff_window;

  const propose = async () => {
    if (!source || !target) return;
    setBusy(true);
    setError(null);
    setProposal(null);
    try {
      setProposal(await api.actionPropose(session.session_id, cutoff, source, target));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const authorize = async () => {
    if (!proposal) return;
    setBusy(true);
    setError(null);
    try {
      setProposal(await api.actionAuthorize(proposal.action_id));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const execute = async (dryRun: boolean) => {
    if (!proposal) return;
    setBusy(true);
    setError(null);
    try {
      setProposal(await api.actionExecute(proposal.action_id, dryRun));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  const trial: TrialPayload | undefined = proposal?.trial;
  const policyFailures = proposal?.policy_failures ?? [];

  return (
    <div className="intervene">
      <button className="intervene-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span>Intervene · paired range trial</span>
        <span aria-hidden="true">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="intervene-body">
          <p className="muted" style={{ margin: "0 0 4px", fontSize: 11.5 }}>
            One authorized block_edge action on an observed external pair,
            executed against the paired no-action continuation (Section 22).
            Bound to the committed forecast at this cutoff.
          </p>
          {error && <ErrorPanel message={error} />}
          <div className="intervene-step">1 · Select observed pair</div>
          <div style={{ display: "grid", gap: 6 }}>
            <select className="pair-select" value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">Internal host —</option>
              {pairs.map((p) => (
                <option key={p.internal} value={p.internal}>{p.internal}</option>
              ))}
            </select>
            <select className="pair-select" value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="">External endpoint —</option>
              {pairs.filter((p) => !source || p.internal === source).map((p) => (
                <option key={p.external} value={p.external}>{p.external}</option>
              ))}
            </select>
            <button className="btn small" disabled={!source || !target || busy} onClick={propose}>
              {busy ? "Working…" : "Propose action"}
            </button>
          </div>

          {proposal && policyFailures.length > 0 && (
            <div className="error-panel">
              <span aria-hidden="true">⚠</span>
              <span><b>Policy check failed.</b> {policyFailures.join(" · ")}</span>
            </div>
          )}

          {proposal && policyFailures.length === 0 && (
            <>
              <div className="intervene-step">2 · Authorize (human approval)</div>
              {proposal.status === "proposed" && (
                <button className="btn primary small" disabled={busy} onClick={authorize}>
                  Authorize block_edge
                </button>
              )}
              {proposal.status === "authorized" && (
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn small" disabled={busy} onClick={() => execute(true)}>
                    Dry-run paired trial
                  </button>
                  <button className="btn danger small" disabled={busy} onClick={() => execute(false)}>
                    Execute once
                  </button>
                </div>
              )}
            </>
          )}

          {trial && (
            <>
              <div className="intervene-step">3 · Paired outcome</div>
              <div className="metric-row">
                <span className="metric-key">Events averted</span>
                <span className="metric-val">
                  {trial.averted_events.length} of {trial.no_action.events.length}
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-key">Packets blocked</span>
                <span className="metric-val">{trial.action_arm.packets_blocked.toLocaleString()}</span>
              </div>
              <div className="metric-row">
                <span className="metric-key">Benign disruption</span>
                <span className="metric-val">
                  {trial.service_disruption.benign_packet_loss_pct.toFixed(2)}%
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-key">Postcondition</span>
                <span className="metric-val">
                  {trial.postcondition_verified ? "verified" : "not verified"}
                </span>
              </div>
              <p className="muted" style={{ fontSize: 10.5, margin: "8px 0 0" }}>
                {trial.note}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function ForecastView({
  session,
  forecast,
  loading,
  error,
  selectedEntity,
  onSelectEntity,
  cutoffWindow,
  onCutoffChange,
}: {
  session: SessionSummary;
  forecast: ForecastPayload | null;
  loading: boolean;
  error: string | null;
  selectedEntity: string | null;
  onSelectEntity: (name: string) => void;
  cutoffWindow: number;
  onCutoffChange: (cutoff: number) => void;
}) {
  const [horizon, setHorizon] = useState(10);

  const entity = useMemo(
    () => forecast?.entities.find((e) => e.name === selectedEntity) ?? null,
    [forecast, selectedEntity],
  );

  const sorted = useMemo(() => {
    if (!forecast) return [];
    return [...forecast.entities].sort(
      (a, b) => occurrenceAt(b, horizon) - occurrenceAt(a, horizon),
    );
  }, [forecast, horizon]);

  const series = useMemo(() => {
    if (!entity) return [];
    return TASKS.map((task) => {
      const t = taskAt(entity, task.index);
      return {
        key: String(task.index),
        label: task.label,
        color: taskColor(task.index),
        values: t.cumulative_risk ?? [],
        threshold: t.policy_threshold,
      };
    }).filter((s) => s.values.length > 0);
  }, [entity]);

  const novelty = entity ? forecast?.novelty.per_entity?.[entity.name] : null;
  const etaTask = useMemo(() => {
    if (!entity) return null;
    let best: { label: string; seconds: number; condition: string } | null = null;
    for (const t of entity.tasks) {
      if (t.eta && (!best || t.eta.median_seconds < best.seconds)) {
        best = { label: t.task_label, seconds: t.eta.median_seconds, condition: t.eta.condition };
      }
    }
    return best;
  }, [entity]);

  const record = forecast?.record;

  return (
    <div className="fade-in">
      <div className="ws-toolbar">
        <div>
          <div className="ws-title">{session.title}</div>
          <div className="ws-sub">
            Cutoff window {cutoffWindow} · {Math.round(cutoffWindow * 0.5)} min into capture ·
            {" "}{forecast?.model.members ?? "—"}-member ensemble ·
            {" "}compute {forecast?.compute_seconds?.toFixed(2) ?? "—"}s
          </div>
        </div>
        <span className="spacer" />
        <label className="muted" htmlFor="cutoff-select" style={{ fontSize: 11 }}>
          Cutoff
        </label>
        <select
          id="cutoff-select"
          className="action-select"
          style={{ minWidth: 150 }}
          value={cutoffWindow}
          onChange={(e) => onCutoffChange(Number(e.target.value))}
        >
          {session.valid_cutoffs.map((c) => (
            <option key={c} value={c}>
              window {c} · {Math.round(c * 0.5)}m
            </option>
          ))}
        </select>
        <div className="horizon-tabs" role="tablist" aria-label="forecast horizon">
          {HORIZONS.map((h) => (
            <button
              key={h.minutes}
              role="tab"
              aria-selected={horizon === h.bins}
              className={horizon === h.bins ? "active" : ""}
              onClick={() => setHorizon(h.bins)}
            >
              {h.label}
            </button>
          ))}
        </div>
      </div>

      {error && <ErrorPanel message={error} />}

      {loading && !forecast && (
        <div className="workspace">
          <div className="workspace-col">
            <div className="workspace-col-head">Entities</div>
            <div className="workspace-col-body" style={{ padding: 12 }}>
              {Array.from({ length: 10 }).map((_, i) => (
                <Skeleton key={i} height={38} />
              ))}
            </div>
          </div>
          <div className="workspace-col">
            <div className="workspace-col-head">Observed network</div>
            <div className="workspace-col-body" style={{ padding: 12 }}>
              <Skeleton height={420} />
            </div>
          </div>
          <div className="workspace-col">
            <div className="workspace-col-head">Inspection</div>
            <div className="workspace-col-body" style={{ padding: 12 }}>
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} height={54} />
              ))}
            </div>
          </div>
        </div>
      )}

      {forecast && (
        <div className="workspace">
          {/* ---- entities ------------------------------------------------ */}
          <div className="workspace-col">
            <div className="workspace-col-head">
              <span>Entities</span>
              <span style={{ letterSpacing: 0 }}>
                {forecast.entities.filter((e) => e.tasks.some((t) => t.alerting)).length} alerting
              </span>
            </div>
            <div className="workspace-col-body">
              {sorted.map((e) => (
                <EntityRow
                  key={e.name}
                  entity={e}
                  bins={horizon}
                  selected={e.name === selectedEntity}
                  onSelect={onSelectEntity}
                />
              ))}
            </div>
          </div>

          {/* ---- network ------------------------------------------------- */}
          <div className="workspace-col">
            <div className="workspace-col-head">
              <span>Observed network · cutoff {cutoffWindow}</span>
              <span style={{ letterSpacing: 0, textTransform: "none" }}>
                {forecast.graph.nodes.length} entities ·
                {" "}{forecast.graph.observed_edges.length} observed pairs
              </span>
            </div>
            <div className="workspace-col-body" style={{ display: "flex", flexDirection: "column" }}>
              <div className="graph-region">
                <GraphView
                  nodes={forecast.graph.nodes}
                  observedEdges={forecast.graph.observed_edges}
                  predictedEdges={forecast.paths.candidate_edges}
                  cutoffWindow={forecast.cutoff_window}
                  selectedEntity={selectedEntity}
                  onSelectEntity={onSelectEntity}
                />
              </div>
            </div>
          </div>

          {/* ---- inspection ---------------------------------------------- */}
          <div className="workspace-col">
            <div className="workspace-col-head"><span>Inspection</span></div>
            <div className="workspace-col-body">
              {entity ? (
                <>
                  <div className="detail-head">
                    <div className="detail-name">{entity.name}</div>
                    <div className="detail-role">{entity.role} · internal scope entity</div>
                  </div>

                  <div className="detail-block">
                    <div className="detail-label">Cumulative risk · next {horizon * 30 / 60} min</div>
                    {series.length > 0 ? (
                      <RiskTimeline
                        series={series}
                        binSeconds={30}
                        horizonMinutes={horizon * 30 / 60}
                        height={190}
                        focusTask={null}
                      />
                    ) : (
                      <div className="muted" style={{ fontSize: 12 }}>
                        No supported task forecasts for this entity.
                      </div>
                    )}
                  </div>

                  <div className="detail-block">
                    <div className="detail-label">Targets</div>
                    {entity.tasks.map((t) => {
                      const risk =
                        t.cumulative_risk
                          ? t.cumulative_risk[Math.min(horizon, t.cumulative_risk.length) - 1]
                          : null;
                      return (
                        <div
                          key={t.task_index}
                          className={`task-row ${risk == null ? "abstained" : ""}`}
                          title={
                            t.eta_withheld_reason ??
                            (t.calibration_status !== "not_applicable"
                              ? `calibration: ${t.calibration_status}`
                              : t.task_label)
                          }
                        >
                          <span className="task-dot" style={{ background: taskColor(t.task_index) }} />
                          <span className="task-name">{t.task_label}</span>
                          <span className="task-eta">
                            {t.eta
                              ? `~${Math.floor(t.eta.median_seconds / 60)}m`
                              : t.alerting
                                ? "alerting"
                                : ""}
                          </span>
                          <span
                            className="task-risk"
                            style={{ color: risk != null ? riskColor(riskLevel(risk)) : undefined }}
                          >
                            {risk == null ? "—" : pct(risk)}
                          </span>
                        </div>
                      );
                    })}
                  </div>

                  <div className="detail-block">
                    <div className="detail-label">Sentinel · trust</div>
                    <div className="state-line">
                      <span
                        className={`state-marker ${
                          novelty?.status === "novel"
                            ? "novel"
                            : novelty?.status === "reference_like"
                              ? "ok"
                              : "off"
                        }`}
                        aria-hidden="true"
                      />
                      <span>
                        {novelty?.status === "novel"
                          ? `Elevated novelty — ${novelty.residual_score?.toFixed(1) ?? "?"}σ residual (unexpectedness, not attack probability)`
                          : novelty?.status === "reference_like"
                            ? "Reference-like behavior"
                            : "Novelty unavailable"}
                      </span>
                    </div>
                    {etaTask && (
                      <div className="metric-row" style={{ marginTop: 6 }}>
                        <span className="metric-key">Nearest conditional ETA</span>
                        <span className="metric-val">
                          {Math.floor(etaTask.seconds / 60)}:
                          {String(Math.round(etaTask.seconds % 60)).padStart(2, "0")} · {etaTask.label}
                        </span>
                      </div>
                    )}
                    <div className="metric-row">
                      <span className="metric-key">Calibration</span>
                      <span className="metric-val">
                        {entity.tasks.filter((t) => t.calibration_status === "fitted").length > 0
                          ? "I.4 fitted"
                          : "uncalibrated / abstained"}
                      </span>
                    </div>
                  </div>

                  {record?.provenance && (
                    <div className="detail-block">
                      <div className="detail-label">Sealed forecast</div>
                      <div className="hash-chip" title={record.forecast_hash}>
                        <span>{record.forecast_hash.slice(0, 20)}…</span>
                        <button
                          onClick={() => navigator.clipboard?.writeText(record.forecast_hash)}
                          aria-label="copy forecast hash"
                        >
                          copy
                        </button>
                      </div>
                      <div className="metric-row" style={{ marginTop: 6 }}>
                        <span className="metric-key">Legal prefix</span>
                        <span className="metric-val mono" style={{ fontSize: 10.5 }}>
                          {record.provenance.legal_prefix_hash.slice(0, 16)}…
                        </span>
                      </div>
                    </div>
                  )}

                  {session.synthetic && <Intervene forecast={forecast} session={session} />}
                </>
              ) : (
                <div className="empty-state">
                  <span className="glyph">◍</span>
                  Select an entity to inspect its forecast.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
