// Attack-path screen (K.2, Section 20): typed-event path hypotheses with
// explicit mass accounting — ranked paths, no-event mass, outside-candidate
// mass and truncated search mass. Path products are NEVER labeled calibrated
// attack-path probabilities; observed / predicted / hypothesized edges keep
// distinct legends.

import { useMemo, useState } from "react";
import type { ForecastPayload } from "../types";
import { TASKS } from "../types";
import { ErrorPanel, Skeleton, Tile, pct, useCountUp } from "../components/charts";
import { GraphView } from "../components/GraphView";

function MassTile({ label, value, tone }: { label: string; value: number; tone?: string }) {
  const animated = useCountUp(value);
  return (
    <Tile
      label={label}
      value={`${(animated * 100).toFixed(1)}%`}
      tone={tone as never}
      foot="decoder mass"
    />
  );
}

function PathRow({
  rank,
  path,
}: {
  rank: number;
  path: { marks: { task_index: number; source: string; target: string; time_window_seconds: [number, number] | null }[]; probability: number; terminal: string };
}) {
  const animated = useCountUp(path.probability);
  return (
    <div className="path-row">
      <span className="rank mono">{rank}</span>
      <div className="marks">
        {path.marks.length === 0 && <span className="muted">no events in horizon</span>}
        {path.marks.map((m, i) => (
          <span className="mark" key={i}>
            {i > 0 && <span className="mark-arrow" aria-hidden="true">→</span>}
            <span className="mark-task" style={{ color: `var(--task-${m.task_index})` }}>
              {TASKS[m.task_index]?.label ?? `task ${m.task_index}`}
            </span>
            <span className="mono mark-pair">
              {m.source.split(".")[0]} → {m.target.split(".")[0]}
            </span>
            <span className="muted">
              {m.time_window_seconds
                ? `+${m.time_window_seconds[0] / 60}–${m.time_window_seconds[1] / 60}m`
                : ""}
            </span>
          </span>
        ))}
      </div>
      <span className="prob mono">{(animated * 100).toFixed(2)}%</span>
      <span className={`tag ${path.terminal === "stop" ? "benign" : "synth"}`}>
        {path.terminal === "stop" ? "ends (no more events)" : path.terminal === "depth" ? "search depth cut" : "outside candidates"}
      </span>
    </div>
  );
}

export function PathsView({
  forecast,
  loading,
  error,
}: {
  forecast: ForecastPayload | null;
  loading: boolean;
  error: string | null;
}) {
  const [showGraph, setShowGraph] = useState(true);
  const paths = forecast?.paths;
  const supported = paths?.status === "supported";
  const ranked = useMemo(() => paths?.ranked_paths?.slice(0, 8) ?? [], [paths]);

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Attack-path hypotheses</h1>
          <p className="sub">
            Typed-event next-mark decoder (Section 20): autoregressive products
            over the candidate universe, beam width {paths?.beam?.width ?? 8},
            depth {paths?.beam?.depth ?? 4}. Ranked hypotheses —{" "}
            <b>not calibrated attack-path probabilities</b>. Separate task from
            the event-time hazard heads.
          </p>
        </div>
      </div>

      {error && <ErrorPanel message={error} />}
      {loading && !forecast && (
        <div className="grid cols-4 stagger">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} height={86} />
          ))}
        </div>
      )}

      {!supported && !loading && (
        <div className="panel" style={{ marginBottom: 14 }}>
          <div className="empty-state">
            <span className="glyph">◇</span>
            <span>
              Typed-event path search reports <span className="mono">not_supported</span>
              : no trained path bundle. Candidate edges below remain marginal
              future-communication probabilities from the edge head.
            </span>
            <span className="muted">{paths?.note}</span>
          </div>
        </div>
      )}

      {supported && (
        <>
          <div className="grid cols-4 stagger" style={{ marginBottom: 14 }}>
            <MassTile label="No event in horizon" value={paths?.no_event_mass ?? 0} tone="good" />
            <MassTile label="Outside candidates" value={paths?.outside_candidate_mass ?? 0} />
            <MassTile label="Truncated search" value={paths?.truncated_search_mass ?? 0} tone="warn" />
            <Tile
              label="Top path probability"
              value={ranked[0] ? `${(ranked[0].probability * 100).toFixed(2)}%` : "—"}
              foot={`uncalibrated · ${paths?.candidate_pairs?.pair_count ?? 0} candidate pairs`}
            />
          </div>

          <div className="v2-section">
            <div className="v2-section-head">
              <h3>Ranked paths</h3>
              <span className="v2-hint">
                calibrated: false · mass accounting{" "}
                {paths?.mass_accounting_total != null
                  ? paths.mass_accounting_total.toFixed(3)
                  : "—"}
              </span>
            </div>
            <div className="paths-list">
              {ranked.length === 0 && (
                <div className="empty-state">
                  <span className="glyph">◌</span>
                  No path hypotheses survived the beam.
                </div>
              )}
              {ranked.map((p, i) => (
                <PathRow key={i} rank={i + 1} path={p} />
              ))}
            </div>
          </div>
        </>
      )}

      <div className="v2-section">
        <div className="v2-section-head">
          <h3>Candidate communication edges</h3>
          <button className="btn ghost small" onClick={() => setShowGraph((v) => !v)} aria-pressed={showGraph}>
            {showGraph ? "Table view" : "Graph view"}
          </button>
        </div>
        {forecast ? (
          showGraph ? (
            <div className="graph-region" style={{ background: "var(--surface-1)", borderRadius: "var(--radius-v2)" }}>
              <GraphView
                nodes={forecast.graph.nodes}
                observedEdges={forecast.graph.observed_edges}
                predictedEdges={paths?.candidate_edges ?? []}
                cutoffWindow={forecast.cutoff_window}
                selectedEntity={null}
                onSelectEntity={() => undefined}
              />
            </div>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Target</th>
                    <th className="num">Marginal probability</th>
                  </tr>
                </thead>
                <tbody>
                  {(paths?.candidate_edges ?? []).slice(0, 12).map((e) => (
                    <tr key={`${e.source}->${e.target}`}>
                      <td className="host-name">{e.source}</td>
                      <td className="host-name">{e.target}</td>
                      <td className="num">{pct(e.probability)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <div className="muted">Run a forecast to see candidate edges.</div>
        )}
      </div>
    </div>
  );
}
