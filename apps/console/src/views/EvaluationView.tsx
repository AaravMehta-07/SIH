// Evaluation screen (K.2): baseline comparisons, independent sample counts,
// confidence intervals, calibration/coverage slices. Gates report
// pass/fail/inconclusive — a small test set yields inconclusive, never a
// fabricated pass (M.5).

import type { EvaluationPayload } from "../types";
import { TASKS } from "../types";
import {
  ErrorPanel,
  LoadingPanel,
  ReliabilityChart,
  TaskBars,
  Tile,
} from "../components/charts";

export function EvaluationView({
  evaluation,
  loading,
  error,
}: {
  evaluation: EvaluationPayload | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading && !evaluation) {
    return (
      <div className="fade-in">
        <div className="view-header">
          <div>
            <h1>Evaluation</h1>
          </div>
        </div>
        <div className="panel">
          <LoadingPanel label="Loading locked-test report…" />
        </div>
      </div>
    );
  }

  const report = evaluation?.locked_test_report ?? null;

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Evaluation</h1>
          <p className="sub">
            Locked-test results from the frozen Section-35 profile, with baselines,
            bootstrap intervals and calibration slices. Statistical gates are
            evidence about the synthetic corpus — not measured real-world
            performance.
          </p>
        </div>
      </div>

      {error && <ErrorPanel message={error} />}
      {!evaluation && !error && (
        <div className="panel">
          <div className="empty-state">
            <span className="glyph">◍</span>
            Evaluation unavailable — is the API running?
          </div>
        </div>
      )}

      {evaluation && (
        <>
          {/* golden example */}
          <div className="panel" style={{ marginBottom: 14 }}>
            <div className="panel-head">
              <h2>Golden contract check (Section 35, example 1)</h2>
              <span className="hint">hand-computed fixtures must match exactly</span>
            </div>
            <div className="panel-body" style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
              <div>
                <div className="muted">hazards [0.10, 0.20, 0.30] →</div>
                <div className="mono" style={{ fontSize: 12.5, marginTop: 4 }}>
                  cumulative {evaluation.golden_example_1.cumulative_risk.map((v) => v.toFixed(3)).join(", ")}
                </div>
                <div className="mono" style={{ fontSize: 12.5 }}>
                  expected&nbsp;&nbsp; {evaluation.golden_example_1.expected_cumulative_risk.map((v) => v.toFixed(3)).join(", ")}
                </div>
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <span className={`tag ${evaluation.golden_example_1.cumulative_matches ? "benign" : "attack"}`}>
                  {evaluation.golden_example_1.cumulative_matches ? "✓ cumulative" : "✗ cumulative"}
                </span>
                <span className={`tag ${evaluation.golden_example_1.no_event_matches ? "benign" : "attack"}`}>
                  {evaluation.golden_example_1.no_event_matches ? "✓ no-event mass" : "✗ no-event mass"}
                </span>
                <span className={`tag ${evaluation.golden_example_1.conditional_median_bin === evaluation.golden_example_1.expected_median_bin ? "benign" : "attack"}`}>
                  {evaluation.golden_example_1.conditional_median_bin === evaluation.golden_example_1.expected_median_bin ? "✓" : "✗"} conditional median = bin {evaluation.golden_example_1.conditional_median_bin ?? "unavailable"}
                </span>
              </div>
            </div>
          </div>

          {!report && (
            <div className="panel">
              <div className="empty-state">
                <span className="glyph">⧗</span>
                No locked-test report yet.
                <span className="muted">
                  Run <span className="mono">python scripts/train_profile.py</span> then{" "}
                  <span className="mono">python scripts/evaluate_profile.py</span> to produce one.
                </span>
              </div>
            </div>
          )}

          {report && (
            <>
              <div className="tiles" style={{ marginBottom: 14 }}>
                <Tile
                  label="Event recall"
                  value={report.metrics.event_recall.toFixed(2)}
                  foot={`≥ 0.50 target · bootstrap CI [${report.metrics.event_recall_bootstrap.ci_low?.toFixed(2) ?? "—"}, ${report.metrics.event_recall_bootstrap.ci_high?.toFixed(2) ?? "—"}] · ${report.metrics.event_recall_bootstrap.units} episodes`}
                  tone={report.metrics.event_recall >= 0.5 ? "good" : "serious"}
                />
                <Tile
                  label="Precision"
                  value={report.metrics.precision.toFixed(2)}
                  foot={`${report.metrics.matched_events} matched / ${report.metrics.unmatched_alerts} unmatched alerts`}
                />
                <Tile
                  label="False alerts / 100 asset-h"
                  value={report.metrics.false_alerts_per_100_asset_hours.toFixed(2)}
                  foot={`≤ 1.0 target · ${report.metrics.asset_hours.toFixed(1)} observed asset-hours`}
                  tone={report.metrics.false_alerts_per_100_asset_hours <= 1 ? "good" : "critical"}
                />
                <Tile
                  label="ECE @ 5 min"
                  value={report.metrics.ece_300s.toFixed(3)}
                  foot={`≤ 0.05 target · Brier ${report.metrics.brier_300s.toFixed(4)} (n=${report.metrics.brier_n})`}
                  tone={report.metrics.ece_300s <= 0.05 ? "good" : "warn"}
                />
                <Tile
                  label="Median lead time"
                  value={
                    report.metrics.lead_time_seconds_median != null
                      ? String(Math.round(report.metrics.lead_time_seconds_median))
                      : "—"
                  }
                  suffix={report.metrics.lead_time_seconds_median != null ? "s" : undefined}
                  foot="among warned events (EV01: misses stay counted)"
                  tone="accent"
                />
              </div>

              <div className="grid cols-2" style={{ marginBottom: 14 }}>
                <div className="panel">
                  <div className="panel-head">
                    <h2>Gates</h2>
                    <span className="hint">pass · fail · inconclusive (never fabricated)</span>
                  </div>
                  <div className="panel-body flush table-wrap">
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Gate</th>
                          <th className="num">Value</th>
                          <th className="num">Target</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.gates.map((g) => (
                          <tr key={g.name}>
                            <td>{g.name}</td>
                            <td className="num mono">
                              {g.value != null ? g.value.toFixed(3) : "—"}
                            </td>
                            <td className="num mono muted">
                              {g.threshold != null ? g.threshold : "—"}
                            </td>
                            <td>
                              <span
                                className={`tag ${g.status === "pass" ? "benign" : g.status === "fail" ? "attack" : ""}`}
                                title={g.reason}
                              >
                                {g.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="panel">
                  <div className="panel-head">
                    <h2>Reliability @ 5 min</h2>
                    <span className="hint">marker size = bin count · dashed = perfect</span>
                  </div>
                  <div className="panel-body">
                    <ReliabilityChart bins={report.metrics.reliability_300s.bins} />
                  </div>
                </div>
              </div>

              <div className="grid cols-2">
                <div className="panel">
                  <div className="panel-head">
                    <h2>Average precision by target</h2>
                    <span className="hint">primary horizon · higher is better</span>
                  </div>
                  <div className="panel-body">
                    <TaskBars
                      values={TASKS.map((t) => ({
                        task: t.index,
                        label: t.label,
                        value: report.per_task[String(t.index)]?.ap ?? null,
                      }))}
                    />
                    <div className="muted" style={{ marginTop: 10 }}>
                      Tasks with no test positives report "—" honestly.
                    </div>
                  </div>
                </div>

                <div className="panel">
                  <div className="panel-head">
                    <h2>Baselines & coverage</h2>
                    <span className="hint">same legal information (M.2)</span>
                  </div>
                  <div className="panel-body">
                    <dl className="kv" style={{ marginBottom: 12 }}>
                      {Object.entries(report.baselines)
                        .filter(([, v]) => typeof v === "number")
                        .map(([k, v]) => (
                          <div key={k} style={{ display: "contents" }}>
                            <dt>{k}</dt>
                            <dd>{(v as number).toFixed(4)}</dd>
                          </div>
                        ))}
                    </dl>
                    <table className="data">
                      <thead>
                        <tr>
                          <th>Family</th>
                          <th className="num">Records</th>
                          <th className="num">Events (5 min)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(report.per_family).map(([fam, row]) => (
                          <tr key={fam}>
                            <td>{fam}</td>
                            <td className="num">{row.prediction_records}</td>
                            <td className="num">{row.primary_horizon_events}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <div className="muted" style={{ marginTop: 14 }}>{report.note}</div>
            </>
          )}
        </>
      )}
    </div>
  );
}
