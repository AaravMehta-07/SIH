// Replay screen (K.2): prefix time separated from reveal controls; the
// prediction process cannot retrieve future labels — only /reveal returns
// them. After reveal: correct warnings, misses, false alerts and lead
// times, scored without concealment.

import { useState } from "react";
import type { ForecastPayload, RevealPayload, SessionSummary } from "../types";
import { TASKS } from "../types";
import { ErrorPanel, LoadingPanel, Tile, pct, taskColor } from "../components/charts";

export function ReplayView({
  session,
  forecast,
  cutoffWindow,
  onCutoffChange,
}: {
  session: SessionSummary;
  forecast: ForecastPayload | null;
  cutoffWindow: number;
  onCutoffChange: (cutoff: number) => void;
}) {
  const [reveal, setReveal] = useState<RevealPayload | null>(null);
  const [revealing, setRevealing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cutoffs = session.valid_cutoffs;
  const index = cutoffs.indexOf(cutoffWindow);

  const doReveal = async () => {
    setRevealing(true);
    setError(null);
    try {
      const response = await fetch(
        `/v1/sessions/${session.session_id}/reveal`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cutoff_window: cutoffWindow }),
        },
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body?.message ?? response.statusText);
      }
      setReveal((await response.json()) as RevealPayload);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setRevealing(false);
    }
  };

  const alerting = (forecast?.entities ?? []).flatMap((e) =>
    e.tasks.filter((t) => t.alerting).map((t) => ({ entity: e.name, task: t })),
  );

  const outcomeStyle = (outcome: string) =>
    outcome === "correct_warning"
      ? "good"
      : outcome === "false_alert"
        ? "critical"
        : "warn";

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Sealed replay</h1>
          <p className="sub">
            Advance the decision cutoff through the capture, forecast at each
            point, then reveal the withheld ground truth. Time is virtual replay
            time; the forecast endpoint never sees future labels (SE02).
          </p>
        </div>
        <button className="btn primary" onClick={doReveal} disabled={revealing}>
          {revealing ? "Revealing…" : "Reveal ground truth"}
        </button>
      </div>

      {error && <ErrorPanel message={error} />}
      {revealing && (
        <div className="panel">
          <LoadingPanel label="Evaluator-side reveal (separate authority)…" />
        </div>
      )}

      <div className="panel" style={{ marginBottom: 14 }}>
        <div className="scrubber">
          <input
            type="range"
            min={0}
            max={cutoffs.length - 1}
            value={Math.max(index, 0)}
            onChange={(e) => onCutoffChange(cutoffs[Number(e.target.value)])}
            aria-label="decision cutoff"
          />
          <div className="scrub-marks">
            <span>window {cutoffs[0]} · {Math.round(cutoffs[0] * 0.5)}m</span>
            <span style={{ color: "var(--ink-2)" }}>
              cutoff window {cutoffWindow} · {Math.round(cutoffWindow * 0.5)}m into capture
            </span>
            <span>window {cutoffs[cutoffs.length - 1]} · {Math.round(cutoffs[cutoffs.length - 1] * 0.5)}m</span>
          </div>
        </div>
      </div>

      <div className="grid cols-2" style={{ marginBottom: 14 }}>
        <div className="panel">
          <div className="panel-head">
            <h2>Forecast state at cutoff</h2>
            <span className="hint">the prediction side</span>
          </div>
          <div className="panel-body">
            {alerting.length === 0 ? (
              <div className="empty-state">
                <span className="glyph">◦</span>
                No alerts at this cutoff — the honest quiet state.
              </div>
            ) : (
              <table className="data">
                <thead>
                  <tr>
                    <th>Entity</th>
                    <th>Target</th>
                    <th className="num">5-min risk</th>
                    <th className="num">Threshold</th>
                  </tr>
                </thead>
                <tbody>
                  {alerting.slice(0, 10).map((a, i) => (
                    <tr key={i}>
                      <td className="host-name">{a.entity}</td>
                      <td style={{ color: taskColor(a.task.task_index) }}>{a.task.task_label}</td>
                      <td className="num">{pct(a.task.cumulative_risk?.[9] ?? null)}</td>
                      <td className="num muted">
                        {a.task.policy_threshold != null ? pct(a.task.policy_threshold) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {reveal && (
          <div className="panel">
            <div className="panel-head">
              <h2>Reveal — ground truth</h2>
              <span className="hint">evaluator side · {reveal.note}</span>
            </div>
            <div className="panel-body flush table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Entity</th>
                    <th>Event</th>
                    <th className="num">Window</th>
                    <th className="num">vs cutoff</th>
                  </tr>
                </thead>
                <tbody>
                  {reveal.events.map((e, i) => (
                    <tr key={i}>
                      <td className="host-name">{e.entity}</td>
                      <td style={{ color: taskColor(e.task_index) }}>
                        {e.task_label}
                        {e.label_tier === "weak_proxy" && (
                          <span className="muted"> · proxy</span>
                        )}
                      </td>
                      <td className="num mono">{e.event_window}</td>
                      <td className="num">
                        {e.relative_to_cutoff > 0
                          ? `+${e.relative_to_cutoff}w`
                          : `${e.relative_to_cutoff}w`}
                      </td>
                    </tr>
                  ))}
                  {reveal.events.length === 0 && (
                    <tr>
                      <td colSpan={4}>
                        <div className="empty-state">
                          No attack events in this capture (benign episode).
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {reveal?.forecast_comparison && (
        <>
          <div className="section-label">Scored comparison — no concealment</div>
          <div className="tiles" style={{ marginBottom: 12 }}>
            <Tile
              label="Correct warnings"
              value={String(
                reveal.forecast_comparison.filter((c) => c.outcome === "correct_warning").length,
              )}
              tone="good"
            />
            <Tile
              label="Early (outside horizon)"
              value={String(
                reveal.forecast_comparison.filter((c) => c.outcome === "early_warning_outside_horizon").length,
              )}
              tone="warn"
            />
            <Tile
              label="False alerts"
              value={String(
                reveal.forecast_comparison.filter((c) => c.outcome === "false_alert").length,
              )}
              tone="critical"
            />
            <Tile
              label="Missed events"
              value={String(
                reveal.events.filter(
                  (e) =>
                    e.relative_to_cutoff > 0 &&
                    !reveal.forecast_comparison?.some(
                      (c) =>
                        c.entity === e.entity &&
                        c.task_index === e.task_index &&
                        c.outcome === "correct_warning",
                    ),
                ).length,
              )}
              foot="events with no qualifying alert stay visible (EV01)"
              tone="serious"
            />
          </div>
          <div className="panel">
            <div className="panel-body flush table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Entity</th>
                    <th>Target</th>
                    <th>Outcome</th>
                    <th className="num">Lead time</th>
                  </tr>
                </thead>
                <tbody>
                  {reveal.forecast_comparison.map((c, i) => (
                    <tr key={i}>
                      <td className="host-name">{c.entity}</td>
                      <td style={{ color: taskColor(c.task_index) }}>
                        {TASKS[c.task_index]?.label ?? c.task_index}
                      </td>
                      <td>
                        <span className={`tag ${outcomeStyle(c.outcome) === "good" ? "benign" : "attack"}`}>
                          {c.outcome.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="num">
                        {c.lead_seconds != null ? `${c.lead_seconds}s` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
