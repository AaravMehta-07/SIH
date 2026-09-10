// Forecast screen (K.2): the operational core — scope/entity/task selection,
// cutoff and emission times, horizon selector, cumulative-risk timeline,
// conditional ETA with its conditions, coverage, health and the sealed
// record receipt. Unsupported tasks stay visible with reasons, never zero.

import { useMemo, useState } from "react";
import type { ForecastPayload, SessionSummary } from "../types";
import { TASKS } from "../types";
import {
  ErrorPanel,
  LoadingPanel,
  RiskTimeline,
  Skeleton,
  Tile,
  entityMaxOccurrence,
  pct,
  riskLevel,
  taskAt,
  taskColor,
} from "../components/charts";
import { GraphView } from "../components/GraphView";

const HORIZONS = [
  { minutes: 5, bins: 10, label: "5 min" },
  { minutes: 15, bins: 30, label: "15 min" },
  { minutes: 30, bins: 60, label: "30 min" },
];

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
  const [focusTask, setFocusTask] = useState<number | null>(null);

  const entity = useMemo(
    () => forecast?.entities.find((e) => e.name === selectedEntity) ?? null,
    [forecast, selectedEntity],
  );

  const sorted = useMemo(() => {
    if (!forecast) return [];
    return [...forecast.entities].sort(
      (a, b) =>
        entityMaxOccurrence(b, horizon) - entityMaxOccurrence(a, horizon),
    );
  }, [forecast, horizon]);

  const alertingCount = useMemo(
    () =>
      forecast?.entities.reduce(
        (n, e) => n + e.tasks.filter((t) => t.alerting).length,
        0,
      ) ?? 0,
    [forecast],
  );

  const maxEta = useMemo(() => {
    if (!forecast) return null;
    let best: { entity: string; seconds: number; task: string } | null = null;
    for (const e of forecast.entities) {
      for (const t of e.tasks) {
        if (t.eta && (!best || t.eta.median_seconds < best.seconds)) {
          best = {
            entity: e.name,
            seconds: t.eta.median_seconds,
            task: t.task_label,
          };
        }
      }
    }
    return best;
  }, [forecast]);

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

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>{session.title}</h1>
          <p className="sub">
            Decision cutoff window {cutoffWindow} ({Math.round(cutoffWindow * 0.5)} min
            into the capture) · history {forecast?.coverage.history_windows ?? 20} windows ·
            horizon 30 min modeled · {forecast?.model.members ?? 5}-member ensemble
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <label className="muted" htmlFor="cutoff-select">Cutoff</label>
          <select
            id="cutoff-select"
            className="btn ghost small"
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
      </div>

      {error && <ErrorPanel message={error} />}

      <div className="tiles" style={{ marginBottom: 16 }}>
        <Tile
          label="Alerting entities"
          value={String(alertingCount)}
          foot={`policy: calibrated threshold per target`}
          tone={alertingCount > 0 ? "critical" : "good"}
        />
        <Tile
          label="Nearest conditional ETA"
          value={
            maxEta
              ? `${Math.floor(maxEta.seconds / 60)}:${String(Math.round(maxEta.seconds % 60)).padStart(2, "0")}`
              : "withheld"
          }
          suffix={maxEta ? "min" : undefined}
          foot={
            maxEta
              ? `${maxEta.entity} · ${maxEta.task} · given occurrence`
              : "occurrence probability below display threshold"
          }
          tone={maxEta ? "serious" : ""}
        />
        <Tile
          label="Novelty (SENTINEL)"
          value={
            forecast?.novelty.status === "novel"
              ? "novel"
              : forecast?.novelty.status === "reference_like"
                ? "reference-like"
                : "unavailable"
          }
          foot={
            forecast?.novelty.max_residual_score != null
              ? `max residual ${forecast.novelty.max_residual_score.toFixed(1)}σ — not an attack probability`
              : forecast?.novelty.note ?? ""
          }
          tone={forecast?.novelty.status === "novel" ? "warn" : ""}
        />
        <Tile
          label="Compute → ledger"
          value={forecast ? forecast.record.compute_to_ledger_seconds.toFixed(2) : "—"}
          suffix="s"
          foot={forecast ? `sealed ${forecast.record.forecast_hash.slice(0, 16)}…` : ""}
          tone="accent"
        />
      </div>

      <div className="grid forecast-layout" style={{ gridTemplateColumns: "300px minmax(0,1fr)", alignItems: "start" }}>
        {/* entity list */}
        <div className="panel">
          <div className="panel-head">
            <h2>Entities by risk</h2>
            <span className="hint">{horizon}-bin horizon</span>
          </div>
          <div className="panel-body flush table-wrap">
            {loading && !forecast ? (
              <div style={{ padding: 12, display: "grid", gap: 8 }}>
                {Array.from({ length: 8 }).map((_, i) => (
                  <Skeleton key={i} height={34} />
                ))}
              </div>
            ) : (
              <table className="data">
                <tbody>
                  {sorted.map((e) => {
                    const max = entityMaxOccurrence(e, horizon);
                    return (
                      <tr
                        key={e.slot}
                        className="clickable"
                        onClick={() => onSelectEntity(e.name)}
                        style={
                          e.name === selectedEntity
                            ? { background: "var(--accent-dim)" }
                            : undefined
                        }
                      >
                        <td>
                          {e.tasks.some((t) => t.alerting) && <span className="alert-dot" />}
                          <span className="host-name">{e.name}</span>
                        </td>
                        <td className="muted" style={{ fontSize: 11 }}>{e.role}</td>
                        <td className="num">
                          <span className={`risk-cell ${riskLevel(max)}`}>{pct(max, 0)}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* main forecast panel */}
        <div style={{ display: "grid", gap: 14 }}>
          {loading && !forecast && (
            <div className="panel">
              <LoadingPanel label="Running Section-26 forecast: observe → rollout → calibrate → survival → ETA…" />
            </div>
          )}

          {entity && (
            <>
              <div className="panel">
                <div className="panel-head">
                  <h2>
                    Cumulative risk · <span className="host-name">{entity.name}</span>
                  </h2>
                  <span className="hint">
                    click a target in the matrix to focus the timeline
                  </span>
                </div>
                <div className="panel-body">
                  <RiskTimeline
                    series={series}
                    binSeconds={forecast?.bin_seconds ?? 30}
                    horizonMinutes={horizon === 10 ? 5 : horizon === 30 ? 15 : 30}
                    focusTask={focusTask}
                    height={260}
                  />
                  <div className="muted" style={{ marginTop: 8 }}>
                    Dashed line: frozen alert threshold (selection policy fitted on
                    the calibration split). Cumulative probability of the first
                    qualifying event, conditional on no earlier occurrence
                    (Section 12).
                  </div>
                </div>
              </div>

              {/* entity × task matrix */}
              <div className="panel">
                <div className="panel-head">
                  <h2>Target matrix — occurrence by {horizon === 10 ? "5" : horizon === 30 ? "15" : "30"} min</h2>
                </div>
                <div className="panel-body flush table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Target</th>
                        <th className="num">Occurrence</th>
                        <th className="num">Alert</th>
                        <th className="num">Cond. ETA</th>
                        <th className="num">Disagree</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {TASKS.map((task) => {
                        const t = taskAt(entity, task.index);
                        const occ =
                          t.cumulative_risk
                            ? t.cumulative_risk[
                                Math.min(horizon, t.cumulative_risk.length) - 1
                              ]
                            : null;
                        return (
                          <tr
                            key={task.index}
                            className="clickable"
                            onClick={() =>
                              setFocusTask(focusTask === task.index ? null : task.index)
                            }
                          >
                            <td>
                              <span
                                style={{
                                  display: "inline-block",
                                  width: 9,
                                  height: 9,
                                  borderRadius: 3,
                                  background: taskColor(task.index),
                                  marginRight: 8,
                                }}
                              />
                              {task.label}
                              {task.tier === "proxy" && (
                                <span className="muted" style={{ marginLeft: 6 }}>
                                  (weak proxy — not compromise)
                                </span>
                              )}
                            </td>
                            <td className="num">
                              <span className={`risk-cell ${riskLevel(occ)}`}>{pct(occ, 1)}</span>
                            </td>
                            <td className="num">
                              {t.alerting ? (
                                <span style={{ color: "var(--critical)", fontWeight: 650 }}>
                                  ● alert
                                </span>
                              ) : (
                                <span className="muted">—</span>
                              )}
                            </td>
                            <td className="num">
                              {t.eta ? (
                                <span>
                                  {Math.floor(t.eta.median_seconds / 60)}m
                                  {String(Math.round(t.eta.median_seconds % 60)).padStart(2, "0")}s
                                  <span className="muted"> @ {pct(t.eta.occurrence_probability, 0)}</span>
                                </span>
                              ) : (
                                <span className="muted" title={t.eta_withheld_reason ?? ""}>
                                  withheld
                                </span>
                              )}
                            </td>
                            <td className="num">
                              {t.disagreement != null ? pct(t.disagreement, 1) : "—"}
                            </td>
                            <td>
                              {t.status === "supported" ? (
                                <span className="tag benign">{t.calibration_status}</span>
                              ) : (
                                <span className="tag" title={t.eta_withheld_reason ?? ""}>
                                  {t.status}
                                </span>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* tactic tags */}
              <div className="panel">
                <div className="panel-head">
                  <h2>Tactic evidence tags</h2>
                  <span className="hint">multi-label evidence · not a linear kill chain</span>
                </div>
                <div className="panel-body" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {entity.tactic_tags.map((tag, i) => (
                    <div
                      key={tag.tactic}
                      style={{
                        flex: `1 1 150px`,
                        padding: "8px 12px",
                        border: "1px solid var(--border)",
                        borderRadius: 8,
                        background: tag.probability > 0.5 ? "var(--raised)" : "transparent",
                      }}
                    >
                      <div className="muted" style={{ fontSize: 10.5, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                        {tag.tactic.replace(/-/g, " ")}
                      </div>
                      <div style={{ fontWeight: 650, fontSize: 15, marginTop: 1 }}>
                        {pct(tag.probability, 0)}
                      </div>
                      <div style={{ height: 4, borderRadius: 2, background: "var(--chart)", marginTop: 5, overflow: "hidden" }}>
                        <div
                          style={{
                            width: `${Math.max(tag.probability * 100, 1)}%`,
                            height: "100%",
                            background: taskColor(i),
                            opacity: 0.8,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* graph + record */}
          {forecast && (
            <div className="panel">
              <div className="panel-head">
                <h2>Communication graph</h2>
                <span className="hint">
                  observed (solid, weight = recency) vs predicted (dashed)
                </span>
              </div>
              <div className="panel-body">
                <GraphView
                  nodes={forecast.graph.nodes}
                  observedEdges={forecast.graph.observed_edges}
                  predictedEdges={forecast.paths.candidate_edges}
                  cutoffWindow={forecast.cutoff_window}
                  selectedEntity={selectedEntity}
                  onSelectEntity={onSelectEntity}
                />
                <div className="muted" style={{ marginTop: 8 }}>
                  {forecast.paths.note}
                </div>
              </div>
            </div>
          )}

          {forecast && (
            <div className="panel">
              <div className="panel-head">
                <h2>Sealed record</h2>
                <span className="hint">immutable · committed before publication (E.2/E.3)</span>
              </div>
              <div className="panel-body">
                <dl className="kv">
                  <dt>Forecast ID</dt>
                  <dd>{forecast.record.forecast_id}</dd>
                  <dt>Record hash</dt>
                  <dd className="hash">{forecast.record.forecast_hash}</dd>
                  <dt>Published at</dt>
                  <dd>{new Date(Number(forecast.record.published_at_ns) / 1e6).toLocaleTimeString()}</dd>
                  <dt>Coverage</dt>
                  <dd>
                    {forecast.coverage.observed_hosts} hosts ·{" "}
                    {forecast.coverage.sensor_gaps.length === 0
                      ? "no observation gaps"
                      : `${forecast.coverage.sensor_gaps.length} gap(s)`}
                  </dd>
                </dl>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
