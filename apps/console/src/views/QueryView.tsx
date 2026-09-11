// Evidence-request screen (K.2, Section 21): one targeted query type —
// identity/session detail for uncertain credential use. Proposals come from
// the transparent stretch rule; execution returns answered / unavailable /
// denied / expired states. Answers are new observations with their own
// clocks, producing a new forecast version — never rewriting the seal.

import { useCallback, useEffect, useState } from "react";
import type {
  ForecastPayload,
  QueryAnswerPayload,
  QueryProposalsPayload,
  SessionSummary,
} from "../types";
import { api } from "../api";
import { ErrorPanel, LoadingPanel, Tile } from "../components/charts";

const STATUS_TONE: Record<string, string> = {
  answered: "good",
  unavailable: "",
  denied: "serious",
  expired: "warn",
};

function resultLabel(status: string): string {
  if (status === "answered") return "answered — real session records returned";
  if (status === "unavailable") return "unavailable — no identity sensor on host (missingness, not an observation)";
  if (status === "denied") return "denied — elevated authorization required";
  return "expired — request window closed";
}

export function QueryView({
  session,
  forecast,
}: {
  session: SessionSummary;
  forecast: ForecastPayload | null;
}) {
  const [proposals, setProposals] = useState<QueryProposalsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executing, setExecuting] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, QueryAnswerPayload>>({});

  const cutoff = forecast?.cutoff_window ?? session.cutoff_window;

  const load = useCallback(async () => {
    if (!forecast) return;
    setLoading(true);
    setError(null);
    try {
      setProposals(await api.queryProposals(session.session_id, cutoff));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setLoading(false);
    }
  }, [session.session_id, cutoff, forecast]);

  useEffect(() => {
    void load();
  }, [load]);

  const execute = async (proposalId: string) => {
    setExecuting(proposalId);
    setError(null);
    try {
      const answer = await api.queryExecute(
        session.session_id,
        proposalId,
        cutoff,
      );
      setAnswers((prev) => ({ ...prev, [proposalId]: answer }));
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setExecuting(null);
    }
  };

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Evidence requests</h1>
          <p className="sub">
            One targeted query (Section 21): identity/session detail for
            uncertain credential use. The default stretch policy is a
            transparent rule — propose when an entity's lateral-movement
            probability is elevated (
            {proposals
              ? `${proposals.policy.uncertain_rule.relative_elevation}× the scope median, above ${proposals.policy.uncertain_rule.absolute_floor}`
              : "1.5× the scope median"}
            ) but not confidently alarming — not a learned selector. Waiting
            and acting immediately remain the comparison policies.
          </p>
        </div>
      </div>

      {error && <ErrorPanel message={error} />}
      {loading && !proposals && <LoadingPanel label="Evaluating the transparent rule…" />}

      {proposals && (
        <>
          <div className="grid cols-4 stagger" style={{ marginBottom: 14 }}>
            <Tile
              label="Identity rows parsed"
              value={String(proposals.identity_quality.parsed_rows)}
              foot={`${proposals.identity_quality.malformed_rows} malformed · ${proposals.identity_quality.adapter}`}
            />
            <Tile
              label="Covered hosts"
              value={String(proposals.identity_quality.coverage.covered_hosts.length)}
              foot="identity sensor coverage"
            />
            <Tile
              label="Proposals at this cutoff"
              value={String(proposals.proposals.length)}
              foot="rule-based, disclosed"
            />
            <Tile
              label="Forecast version"
              value={String(proposals.policy.forecast_version)}
              tone="accent"
              foot="answers create new versions"
            />
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Proposed queries</h2>
              <span className="hint">
                allowlisted · scoped · costed · expiring (Section 21)
              </span>
            </div>
            <div className="panel-body flush">
              {proposals.proposals.length === 0 && (
                <div className="empty-state">
                  <span className="glyph">◌</span>
                  No uncertain credential use at this cutoff — nothing worth
                  querying (§21: acquisition must improve a decision).
                </div>
              )}
              {proposals.proposals.map((p) => {
                const answer = answers[p.proposal_id];
                return (
                  <div className="query-row" key={p.proposal_id}>
                    <div className="query-main">
                      <div>
                        <b className="host-name">{p.entity}</b>
                        <span className="muted"> · lateral-movement p = {p.occurrence_probability.toFixed(2)}</span>
                      </div>
                      <div className="muted" style={{ marginTop: 2 }}>{p.rationale}</div>
                      <div className="card-meta" style={{ marginTop: 6 }}>
                        <span className="tag">{p.query_type}</span>
                        <span className="tag synth">privacy cost {p.cost.privacy}</span>
                        <span className="tag synth">delay {p.cost.delay_seconds}s</span>
                        <span className="tag synth">expires in {p.allowlist.expiry_seconds}s</span>
                      </div>
                    </div>
                    <div className="query-side">
                      <button
                        className="btn small"
                        disabled={executing === p.proposal_id || answer != null}
                        onClick={() => execute(p.proposal_id)}
                      >
                        {answer ? "Answered" : executing === p.proposal_id ? "Requesting…" : "Request"}
                      </button>
                    </div>
                    {answer && (
                      <div className={`query-answer answer-${STATUS_TONE[answer.status] ?? ""} fade-in`}>
                        <div className="answer-head">
                          <span className={`tag ${STATUS_TONE[answer.status] || "synth"}`}>
                            {answer.status}
                          </span>
                          <span>{resultLabel(answer.status)}</span>
                        </div>
                        {answer.status === "answered" && (
                          <div className="table-wrap">
                            <table className="data">
                              <thead>
                                <tr>
                                  <th>Time (ns)</th>
                                  <th>User</th>
                                  <th>Source</th>
                                  <th>Dest</th>
                                  <th>Type</th>
                                  <th>Result</th>
                                </tr>
                              </thead>
                              <tbody>
                                {answer.records.slice(-8).map((r) => (
                                  <tr key={r.session_id}>
                                    <td className="mono">{r.time_ns}</td>
                                    <td className="mono">{r.user}</td>
                                    <td className="host-name">{r.source_host}</td>
                                    <td className="host-name">{r.dest_host}</td>
                                    <td>{r.auth_type}</td>
                                    <td>
                                      <span className={`tag ${r.result === "success" ? "attack" : "benign"}`}>
                                        {r.result}
                                      </span>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        )}
                        <div className="muted" style={{ marginTop: 8 }}>
                          {answer.note}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="disclosure" role="note" style={{ marginTop: 14 }}>
            <span className="icon" aria-hidden="true">ⓘ</span>
            <span>
              Identity telemetry is a separate replay-only modality: analyst
              context and query answers, <b>not a model feature</b> — the
              Section-35 feature registry is frozen. Model scores do not
              change; the answer improves the analyst decision.
            </span>
          </div>
        </>
      )}
    </div>
  );
}
