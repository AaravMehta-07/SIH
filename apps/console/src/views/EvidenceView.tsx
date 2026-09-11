// Evidence screen (K.2): three analyst evidence flows in one place —
// deletion-tested attribution with fidelity, observed rule-based flags, and
// Section 21 evidence requests. Every cited flow belongs to the legal
// prefix (EX02) — no future packet is ever shown.

import { useEffect, useState } from "react";
import type { EvidencePayload, ForecastPayload, SessionSummary } from "../types";
import { TASKS } from "../types";
import { api } from "../api";
import {
  AttributionBars,
  ErrorPanel,
  LoadingPanel,
  Tile,
  pct,
} from "../components/charts";
import { QueryView } from "./QueryView";

type Tab = "attribution" | "flags" | "requests";

export function EvidenceView({
  session,
  forecast,
  selectedEntity,
  onSelectEntity,
  cutoffWindow,
}: {
  session: SessionSummary;
  forecast: ForecastPayload | null;
  selectedEntity: string | null;
  onSelectEntity: (name: string) => void;
  cutoffWindow: number;
}) {
  const [tab, setTab] = useState<Tab>("attribution");
  const [taskIndex, setTaskIndex] = useState(2);
  const [evidence, setEvidence] = useState<EvidencePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const entity = selectedEntity ?? forecast?.entities[0]?.name ?? null;

  useEffect(() => {
    if (!entity || tab !== "attribution") return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setEvidence(null);
    api
      .evidence(session.session_id, entity, taskIndex, cutoffWindow)
      .then((payload) => {
        if (!cancelled) setEvidence(payload);
      })
      .catch((e) => {
        if (!cancelled) setError(String((e as Error).message ?? e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session.session_id, entity, taskIndex, cutoffWindow, tab]);

  const flagged = forecast?.flagged ?? [];

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Evidence</h1>
          <p className="sub">
            Source-linked traffic and measured attribution. Deletion deltas are sensitivity, not causal effects.
          </p>
        </div>
        {tab === "attribution" && (
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <select
              className="action-select"
              value={entity ?? ""}
              onChange={(e) => onSelectEntity(e.target.value)}
              aria-label="entity"
            >
              {(forecast?.entities ?? []).map((e) => (
                <option key={e.slot} value={e.name}>
                  {e.name}
                </option>
              ))}
            </select>
            <select
              className="action-select"
              value={taskIndex}
              onChange={(e) => setTaskIndex(Number(e.target.value))}
              aria-label="target task"
            >
              {TASKS.map((t) => (
                <option key={t.index} value={t.index}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="v2-tabs" role="tablist" aria-label="evidence flows">
        <button
          role="tab"
          aria-selected={tab === "attribution"}
          className={tab === "attribution" ? "active" : ""}
          onClick={() => setTab("attribution")}
        >
          Attribution
        </button>
        <button
          role="tab"
          aria-selected={tab === "flags"}
          className={tab === "flags" ? "active" : ""}
          onClick={() => setTab("flags")}
        >
          Flagged traffic
          {flagged.length > 0 ? ` · ${flagged.length}` : ""}
        </button>
        <button
          role="tab"
          aria-selected={tab === "requests"}
          className={tab === "requests" ? "active" : ""}
          onClick={() => setTab("requests")}
        >
          Evidence requests
        </button>
      </div>

      {tab === "attribution" && (
        <>
          {error && <ErrorPanel message={error} />}
          {loading && (
            <div className="panel">
              <LoadingPanel label="Running grouped-deletion attribution (bounded budget)…" />
            </div>
          )}

          {evidence && !loading && (
            <>
              <div className="tiles stagger" style={{ marginBottom: 16 }}>
                <Tile
                  label="Baseline risk (5 min)"
                  value={pct(evidence.baseline_risk, 1)}
                  foot={`${TASKS[taskIndex].label} · ${entity}`}
                />
                <Tile
                  label="Comprehensiveness"
                  value={evidence.comprehensiveness != null ? pct(evidence.comprehensiveness, 1) : "—"}
                  foot="risk drop when all selected evidence is removed"
                  tone="serious"
                />
                <Tile
                  label="Random baseline"
                  value={
                    evidence.random_baseline_comprehensiveness != null
                      ? pct(evidence.random_baseline_comprehensiveness, 1)
                      : "—"
                  }
                  foot="matched-size random deletion (fidelity control)"
                />
                <Tile
                  label="Sufficiency"
                  value={evidence.sufficiency != null ? pct(evidence.sufficiency, 1) : "—"}
                  foot="risk retained when only selected evidence is kept"
                />
              </div>

              <div className="v2-section">
                <div className="v2-section-head">
                  <h3>
                    Attribution · {entity} · {TASKS[taskIndex].label}
                  </h3>
                  <span className="v2-hint">
                    {evidence.partial ? "partial — bounded budget (K.1)" : "full prefix attribution"}
                  </span>
                </div>
                <AttributionBars
                  items={evidence.evidence.map((e) => ({
                    window_index: e.window_index,
                    delta: e.delta,
                    category: e.category,
                  }))}
                  baseline={evidence.baseline_risk}
                />
                <div className="muted" style={{ marginTop: 8 }}>{evidence.note}</div>
              </div>

              <div className="v2-section">
                <div className="v2-section-head">
                  <h3>Source-linked flows · legal prefix</h3>
                  <span className="v2-hint">observed packets only — no future rows</span>
                </div>
                <div className="table-wrap">
                  <table className="data">
                    <thead>
                      <tr>
                        <th className="num">Window</th>
                        <th>Source</th>
                        <th>Target</th>
                        <th className="num">Port</th>
                        <th>Proto</th>
                        <th className="num">Bytes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {evidence.flows.slice(0, 24).map((f, i) => (
                        <tr key={i}>
                          <td className="num mono">{f.window}</td>
                          <td className="host-name">{f.source}</td>
                          <td className="host-name">{f.target}</td>
                          <td className="num mono">{f.dport}</td>
                          <td>{f.protocol}</td>
                          <td className="num mono">{f.bytes.toLocaleString()}</td>
                        </tr>
                      ))}
                      {evidence.flows.length === 0 && (
                        <tr>
                          <td colSpan={6}>
                            <div className="empty-state">No contributing flows found.</div>
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}
        </>
      )}

      {tab === "flags" && (
        <div className="v2-section">
          <div className="v2-section-head">
            <h3>Observed evidence flags</h3>
            <span className="v2-hint">
              rule-based, detection-style annotations on legal features — never forecasts
            </span>
          </div>
          {flagged.length === 0 ? (
            <div className="empty-state">
              <span className="glyph">◌</span>
              No rule-based flags on this prefix.
            </div>
          ) : (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th className="num">Window</th>
                    <th>Entity</th>
                    <th>Kind</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {flagged.map((f, i) => (
                    <tr key={i}>
                      <td className="num mono">{f.window}</td>
                      <td className="host-name">{f.entity}</td>
                      <td>
                        <span className={`tag ${f.kind === "host" ? "attack" : ""}`}>{f.kind}</span>
                      </td>
                      <td>{f.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === "requests" && <QueryView session={session} forecast={forecast} />}
    </div>
  );
}
