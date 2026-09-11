// Sealed replay (K.2, Section 7/30): the commitment theater. The decision
// cutoff divides PAST OBSERVED from FUTURE LOCKED; the forecast is committed
// with a hash before any reveal; only the evaluator-side /reveal endpoint
// ever returns ground truth (SE02). After reveal: predicted vs actual with
// advance warning and honest outcomes — matched, miss, false alert — scored
// without concealment.

import { useState } from "react";
import { LockKeyhole, ShieldCheck, ArrowRight } from "lucide-react";
import { CopyButton } from "../components/CopyButton";
import type { ForecastPayload, RevealPayload, SessionSummary } from "../types";
import { TASKS } from "../types";
import { api } from "../api";
import { ErrorPanel, LoadingPanel, pct, taskColor } from "../components/charts";

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
  const index = Math.max(cutoffs.indexOf(cutoffWindow), 0);

  const doReveal = async () => {
    setRevealing(true);
    setError(null);
    try {
      setReveal(await api.reveal(session.session_id, cutoffWindow));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setRevealing(false);
    }
  };

  const alerting = (forecast?.entities ?? []).flatMap((e) =>
    e.tasks.filter((t) => t.alerting).map((t) => ({ entity: e.name, task: t })),
  );

  const record = forecast?.record;
  const comparison = reveal?.forecast_comparison ?? [];
  const counts = {
    matched: comparison.filter((c) => c.outcome === "correct_warning").length,
    early: comparison.filter((c) => c.outcome === "early_warning_outside_horizon").length,
    falseAlerts: comparison.filter((c) => c.outcome === "false_alert").length,
    missed: (reveal?.events ?? []).filter(
      (e) =>
        e.relative_to_cutoff > 0 &&
        !comparison.some(
          (c) =>
            c.entity === e.entity &&
            c.task_index === e.task_index &&
            c.outcome === "correct_warning",
        ),
    ).length,
  };

  const eventFor = (entity: string, taskIndex: number) =>
    (reveal?.events ?? []).find(
      (e) => e.entity === entity && e.task_index === taskIndex,
    );

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Sealed replay</h1>
          <p className="sub">
            Commitment before comparison. Virtual replay time; observed outcomes remain separate from forecasts.
          </p>
        </div>
      </div>

      {error && <ErrorPanel message={error} />}

      <div className="theater" style={{ marginBottom: 16 }}>
        <div className="scrubber" style={{ borderBottom: "1px solid var(--hairline)" }}>
          <input
            type="range"
            min={0}
            max={cutoffs.length - 1}
            value={index}
            onChange={(e) => {
              setReveal(null);
              onCutoffChange(cutoffs[Number(e.target.value)]);
            }}
            aria-label="decision cutoff"
          />
          <div className="scrub-marks">
            <span>{Math.round(cutoffs[0] * 0.5)}m</span>
            <span style={{ color: "var(--ink-2)" }}>
              cutoff window {cutoffWindow} · {Math.round(cutoffWindow * 0.5)}m into capture
            </span>
            <span>{Math.round(cutoffs[cutoffs.length - 1] * 0.5)}m</span>
          </div>
        </div>

        {/* past | locked | committed */}
        <div className="theater-strip">
          <div className="t-side">
            <span className="t-label" style={{ color: "var(--ink-2)" }}>Past · observed</span>
            <span className="t-desc">
              {forecast?.coverage.history_windows ?? 20} eligible windows ·
              {" "}{forecast?.coverage.observed_hosts ?? "—"} hosts ·
              {" "}{forecast?.flagged.length ?? 0} flagged signatures
            </span>
          </div>
          <div className="t-lock">
            <span className="lock-glyph" aria-hidden="true">{reveal ? <ShieldCheck size={32} strokeWidth={1.3} /> : <LockKeyhole size={32} strokeWidth={1.3} />}</span>
            <span className="lock-text">{reveal ? "Future revealed" : "Future locked"}</span>
          </div>
          <div className="t-side right">
            <span className="t-label" style={{ color: "var(--accent)" }}>
              Forecast {record?.committed ? "committed" : "pending"}
            </span>
            <span className="t-desc">
              {record
                ? `${(record.compute_to_ledger_seconds ?? 0).toFixed(2)}s compute → ledger`
                : "run a forecast at this cutoff"}
            </span>
            {record && (
              <span className="hash-chip" style={{ marginTop: 4 }}>
                <span>{record.forecast_hash.slice(0, 18)}…</span>
                <CopyButton value={record.forecast_hash} />
              </span>
            )}
          </div>
        </div>

        {/* reveal CTA or outcome board */}
        {!reveal ? (
          <div className="reveal-cta">
            <button className="btn primary" onClick={doReveal} disabled={revealing || !record || forecast?.cutoff_window !== cutoffWindow}>
              {revealing ? "Revealing…" : "Reveal future"}
              <ArrowRight size={15} />
            </button>
            <span className="muted" style={{ fontSize: 11.5 }}>
              Reveal does not modify the committed forecast.
            </span>
          </div>
        ) : (
          <div className="pva-board">
            <div className="pva-cell">
              <div className="pva-tag">Predicted · at cutoff {cutoffWindow}</div>
              {alerting.length === 0 ? (
                <div className="pva-main">No alerts at this cutoff</div>
              ) : (
                alerting.slice(0, 3).map((a, i) => (
                  <div key={i} style={{ marginBottom: 8 }}>
                    <div className="pva-main">
                      <span style={{ color: taskColor(a.task.task_index) }}>
                        {a.task.task_label}
                      </span>{" "}
                      · {a.entity.split(".")[0]}
                    </div>
                    <div className="pva-sub">
                      5-min risk {pct(a.task.cumulative_risk?.[9] ?? null)}
                      {a.task.eta ? ` · conditional ETA ~${Math.floor(a.task.eta.median_seconds / 60)}m` : ""}
                    </div>
                  </div>
                ))
              )}
              {alerting.length > 3 && (
                <div className="pva-sub">+{alerting.length - 3} more alerting targets</div>
              )}
            </div>
            <div className="pva-cell">
              <div className="pva-tag">Actual · revealed</div>
              {comparison.length === 0 ? (
                <div className="pva-sub" style={{ marginTop: 0 }}>
                  {counts.matched + counts.falseAlerts === 0
                    ? "No alerting targets to score at this cutoff."
                    : ""}
                </div>
              ) : (
                comparison.map((c, i) => {
                  const event = eventFor(c.entity, c.task_index);
                  return (
                    <div
                      key={i}
                      style={{ marginBottom: 8, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}
                    >
                      <span
                        className={`outcome-badge ${
                          c.outcome === "correct_warning"
                            ? "matched"
                            : c.outcome === "false_alert"
                              ? "false-alert"
                              : "abstained"
                        }`}
                      >
                        {c.outcome === "correct_warning"
                          ? `Matched · +${Math.round((c.lead_seconds ?? 0) / 60)}m${Math.round(((c.lead_seconds ?? 0) % 60))}s warning`
                          : c.outcome === "false_alert"
                            ? "False alert"
                            : "Early · outside horizon"}
                      </span>
                      <span className="pva-sub" style={{ marginTop: 0 }}>
                        {TASKS[c.task_index]?.label ?? c.task_index} · {c.entity.split(".")[0]}
                        {event ? ` · observed at +${Math.round(((event.event_window - cutoffWindow) * 30) / 60)}m` : ""}
                      </span>
                    </div>
                  );
                })
              )}
              {(counts.missed > 0 || (reveal.events.length === 0 && alerting.length === 0)) && (
                <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                  {counts.missed > 0 && (
                    <span className="outcome-badge miss">
                      {counts.missed} missed event{counts.missed > 1 ? "s" : ""}
                    </span>
                  )}
                  {reveal.events.length === 0 && (
                    <span className="pva-sub" style={{ marginTop: 0 }}>
                      benign capture — no attack events
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* summary strip */}
      {reveal && (
        <div className="v2-section">
          <div className="v2-section-head">
            <h3>Scored outcomes — no concealment</h3>
            <span className="v2-hint">
              {counts.matched} matched · {counts.early} early · {counts.falseAlerts} false · {counts.missed} missed
            </span>
          </div>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Entity</th>
                  <th>Event</th>
                  <th className="num">Event window</th>
                  <th className="num">vs cutoff</th>
                  <th className="num">Lead</th>
                </tr>
              </thead>
              <tbody>
                {reveal.events.map((e, i) => {
                  const scored = comparison.find(
                    (c) => c.entity === e.entity && c.task_index === e.task_index,
                  );
                  return (
                    <tr key={i}>
                      <td className="host-name">{e.entity}</td>
                      <td style={{ color: taskColor(e.task_index) }}>
                        {e.task_label}
                        {e.label_tier === "weak_proxy" && <span className="muted"> · proxy</span>}
                      </td>
                      <td className="num mono">{e.event_window}</td>
                      <td className="num">
                        {e.relative_to_cutoff > 0
                          ? `+${Math.round((e.relative_to_cutoff * 30) / 60)}m`
                          : `${Math.round((e.relative_to_cutoff * 30) / 60)}m`}
                      </td>
                      <td className="num">
                        {scored?.lead_seconds != null
                          ? `${Math.floor(scored.lead_seconds / 60)}:${String(scored.lead_seconds % 60).padStart(2, "0")}`
                          : scored
                            ? "—"
                            : e.relative_to_cutoff > 0
                              ? "missed"
                              : "before cutoff"}
                      </td>
                    </tr>
                  );
                })}
                {reveal.events.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <div className="empty-state">
                        No attack events in this capture (benign episode) — a quiet
                        forecast is the honest outcome.
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {revealing && (
        <div className="panel">
          <LoadingPanel label="Evaluator-side reveal (separate authority)…" />
        </div>
      )}
    </div>
  );
}
