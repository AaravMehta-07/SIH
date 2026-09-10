// Evidence screen (K.2): flagged flow references, deletion-tested
// attribution with fidelity, observed graph context. Every cited flow
// belongs to the legal prefix (EX02) — no future packet is ever shown.

import { useEffect, useState } from "react";
import type { EvidencePayload, ForecastPayload, SessionSummary } from "../types";
import { TASKS } from "../types";
import {
  AttributionBars,
  ErrorPanel,
  LoadingPanel,
  Tile,
  pct,
} from "../components/charts";

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
  const [taskIndex, setTaskIndex] = useState(2);
  const [evidence, setEvidence] = useState<EvidencePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const entity = selectedEntity ?? forecast?.entities[0]?.name ?? null;

  useEffect(() => {
    if (!entity) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setEvidence(null);
    fetch(`/v1/sessions/${session.session_id}/evidence`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity, task_index: taskIndex, cutoff_window: cutoffWindow }),
    })
      .then(async (r) => {
        if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.message ?? r.statusText);
        return r.json() as Promise<EvidencePayload>;
      })
      .then((payload) => {
        if (!cancelled) setEvidence(payload);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e.message ?? e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session.session_id, entity, taskIndex, cutoffWindow]);

  const flagged = forecast?.flagged ?? [];

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Evidence</h1>
          <p className="sub">
            Deletion-tested attribution: remove one prefix window of the entity's
            traffic, recompute features, rerun the model — the score delta is the
            evidence. Fidelity is measured against matched-size random deletion
            (K.1). Deltas are sensitivity, not causal effects.
          </p>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <select
            className="btn ghost small"
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
            className="btn ghost small"
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
      </div>

      {error && <ErrorPanel message={error} />}
      {loading && (
        <div className="panel">
          <LoadingPanel label="Running grouped-deletion attribution (bounded budget)…" />
        </div>
      )}

      {evidence && !loading && (
        <>
          <div className="tiles" style={{ marginBottom: 16 }}>
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

          <div className="panel" style={{ marginBottom: 14 }}>
            <div className="panel-head">
              <h2>
                Attribution · {entity} · {TASKS[taskIndex].label}
              </h2>
              <span className="hint">
                {evidence.partial ? "partial — bounded budget (K.1)" : "full prefix attribution"}
              </span>
            </div>
            <div className="panel-body">
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
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Source-linked flows (legal prefix)</h2>
              <span className="hint">
                rows cited by the attribution — observed packets only
              </span>
            </div>
            <div className="panel-body flush table-wrap">
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

      {flagged.length > 0 && (
        <>
          <div className="section-label">Observed evidence flags (rule-based, detection-style)</div>
          <div className="panel">
            <div className="panel-body flush table-wrap">
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
          </div>
        </>
      )}
    </div>
  );
}
