// Range-action screen (K.2, Sections 22-23): propose one block_edge action
// bound to the committed forecast, pass explicit policy checks and human
// authorization, then execute a paired no-action/action trial in the
// disclosed synthetic range. No "fix everything" button; no real-world
// control effect is claimed.

import { useMemo, useState } from "react";
import type { ActionProposalPayload, ForecastPayload, SessionSummary, TrialEvent } from "../types";
import { TASKS } from "../types";
import { api } from "../api";
import { ErrorPanel, Tile } from "../components/charts";

function fmtNs(ns: string): string {
  const v = Number(ns);
  if (!Number.isFinite(v)) return ns;
  return `${(v / 60_000_000_000).toFixed(1)} min`;
}

function EventList({ title, events, tone }: { title: string; events: TrialEvent[]; tone: "critical" | "good" }) {
  return (
    <div className="trial-arm">
      <div className={`section-label ${tone === "good" ? "good-label" : ""}`}>{title}</div>
      {events.length === 0 ? (
        <div className="muted" style={{ padding: "6px 0" }}>no attack events in the remaining horizon</div>
      ) : (
        events.map((e, i) => (
          <div className="trial-event" key={i}>
            <span className="mark-task" style={{ color: `var(--task-${e.task_index})` }}>
              {TASKS[e.task_index]?.label ?? `task ${e.task_index}`}
            </span>
            <span className="mono">
              {e.source.split(".")[0]} → {e.target.split(".")[0]}
            </span>
            <span className="muted">at {fmtNs(e.time_ns)}</span>
          </div>
        ))
      )}
    </div>
  );
}

export function ActionView({
  session,
  forecast,
}: {
  session: SessionSummary;
  forecast: ForecastPayload | null;
}) {
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [proposal, setProposal] = useState<ActionProposalPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cutoff = forecast?.cutoff_window ?? session.cutoff_window;

  // Candidate blocked pairs: cross-boundary pairs observed on the eligible
  // prefix (graph edges are internal-only, G.2).
  const externalPairs = useMemo(() => {
    const pairs: { internal: string; external: string; packets: number }[] = [];
    const seen = new Set<string>();
    for (const e of forecast?.graph.external_edges ?? []) {
      const aInternal = e.source.endsWith(".local");
      const bInternal = e.target.endsWith(".local");
      if (aInternal === bInternal) continue;
      const internal = aInternal ? e.source : e.target;
      const external = aInternal ? e.target : e.source;
      const key = `${internal}|${external}`;
      if (!seen.has(key)) {
        seen.add(key);
        pairs.push({ internal, external, packets: e.packets });
      }
    }
    return pairs.sort((a, b) => b.packets - a.packets);
  }, [forecast]);

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

  const trial = proposal?.trial ?? null;
  const state = proposal?.status ?? "idle";

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Range action · paired trial</h1>
          <p className="sub">
            One authorized action (Section 22): <span className="mono">block_edge</span>{" "}
            on an observed internal↔external pair, executed against the
            disclosed synthetic range with a paired no-action continuation
            from the same cutoff and seed. Explicit authorization, expiry,
            idempotency and a verified postcondition (Section 23). Simulator
            success is not production proof.
          </p>
        </div>
      </div>

      {error && <ErrorPanel message={error} />}

      {!forecast && (
        <div className="panel">
          <div className="empty-state">
            <span className="glyph">◇</span>
            Run a forecast first — actions bind to the committed forecast hash.
          </div>
        </div>
      )}

      {forecast && (
        <div className="panel" style={{ marginBottom: 14 }}>
          <div className="panel-head">
            <h2>Propose</h2>
            <span className="hint">
              state: <span className="mono">{state}</span> · policy{" "}
              <span className="mono">{proposal?.policy_version ?? "range-demo-policy-1"}</span>
            </span>
          </div>
          <div className="panel-body">
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
              <label style={{ display: "grid", gap: 4 }}>
                <span className="muted">Internal host</span>
                <select value={source} onChange={(e) => setSource(e.target.value)} className="action-select">
                  <option value="">— select —</option>
                  {externalPairs.map((p) => (
                    <option key={p.internal} value={p.internal}>{p.internal}</option>
                  ))}
                </select>
              </label>
              <span style={{ padding: "0 0 8px" }}>↔</span>
              <label style={{ display: "grid", gap: 4 }}>
                <span className="muted">External endpoint</span>
                <select value={target} onChange={(e) => setTarget(e.target.value)} className="action-select">
                  <option value="">— select —</option>
                  {externalPairs
                    .filter((p) => !source || p.internal === source)
                    .map((p) => (
                      <option key={p.external} value={p.external}>{p.external}</option>
                    ))}
                </select>
              </label>
              <button className="btn" disabled={!source || !target || busy} onClick={propose}>
                {busy ? "Working…" : "Propose action"}
              </button>
            </div>
            <div className="muted" style={{ marginTop: 10 }}>
              Observed external pairs only (scope allowlist). Alternatives are
              always shown:{" "}
              {(proposal?.alternatives ?? [
                { action: "no_action", description: "monitor; decide at the next cutoff" },
                { action: "query_first", description: "request identity/session detail first" },
              ]).map((a) => `${a.action} (${a.description})`).join(" · ")}
            </div>
          </div>
        </div>
      )}

      {proposal && (
        <>
          {proposal.policy_failures && proposal.policy_failures.length > 0 && (
            <div className="error-panel">
              <span aria-hidden="true">⚠</span>
              <span>
                <b>Policy check failed.</b>{" "}
                {proposal.policy_failures.join(" · ")} — the proposal is not
                authorizable.
              </span>
            </div>
          )}

          {proposal.authorizable && (
            <div className="panel" style={{ marginBottom: 14 }}>
              <div className="panel-head">
                <h2>Authorize</h2>
                <span className="hint">
                  bound to forecast <span className="mono">{proposal.evidence_binding.forecast_hash.slice(0, 12)}</span>{" "}
                  · expires <span className="mono">{proposal.expiry_ns}</span>
                </span>
              </div>
              <div className="panel-body" style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                <div className="kv" style={{ flex: 1, minWidth: 260 }}>
                  <dt>Action</dt>
                  <dd>{proposal.action_type}: {proposal.parameters.source} ↔ {proposal.parameters.target}</dd>
                  <dt>Reversibility</dt>
                  <dd>{proposal.reversibility}</dd>
                  <dt>Idempotency key</dt>
                  <dd>{proposal.idempotency_key.slice(0, 16)}…</dd>
                  <dt>Uncertainty</dt>
                  <dd>
                    {Object.keys(proposal.uncertainty).length
                      ? JSON.stringify(proposal.uncertainty)
                      : "ensemble disagreement recorded when present"}
                  </dd>
                </div>
                {proposal.status === "proposed" && (
                  <button className="btn primary" disabled={busy} onClick={authorize}>
                    Authorize (human approval)
                  </button>
                )}
                {proposal.status === "authorized" && (
                  <>
                    <button className="btn" disabled={busy} onClick={() => execute(true)}>
                      Dry-run paired trial
                    </button>
                    <button className="btn danger" disabled={busy} onClick={() => execute(false)}>
                      Execute once in range
                    </button>
                  </>
                )}
              </div>
              {proposal.audit && (
                <div className="muted" style={{ padding: "0 16px 12px" }}>
                  audit: {proposal.audit.map((a) => a.to).join(" → ")}
                </div>
              )}
            </div>
          )}

          {trial && (
            <div className="panel">
              <div className="panel-head">
                <h2>Paired trial outcome</h2>
                <span className="hint">
                  {proposal.status} · postcondition{" "}
                  <span className={`tag ${trial.postcondition_verified ? "benign" : "attack"}`}>
                    {trial.postcondition_verified ? "verified" : "not verified"}
                  </span>
                  {trial.dry_run != null && (
                    <span className="tag synth" style={{ marginLeft: 6 }}>
                      {trial.dry_run ? "dry run" : "range execution"}
                    </span>
                  )}
                </span>
              </div>
              <div className="panel-body">
                <div className="grid cols-4 stagger" style={{ marginBottom: 14 }}>
                  <Tile
                    label="Events averted"
                    value={String(trial.averted_events.length)}
                    tone="good"
                    foot={`of ${trial.no_action.events.length} post-cutoff events`}
                  />
                  <Tile
                    label="Packets blocked"
                    value={trial.action_arm.packets_blocked.toLocaleString()}
                    foot="on the blocked pair, post-action"
                  />
                  <Tile
                    label="Benign packet loss"
                    value={`${trial.service_disruption.benign_packet_loss_pct.toFixed(2)}%`}
                    tone={trial.service_disruption.benign_packet_loss_pct < 1 ? "good" : "warn"}
                    foot="collateral disruption"
                  />
                  <Tile
                    label="Reversibility"
                    value="reversible"
                    tone="accent"
                    foot={trial.service_disruption.reversibility}
                  />
                </div>

                <div className="grid cols-2">
                  <div className="trial-arm-wrap">
                    <EventList title="No-action continuation" events={trial.no_action.events} tone="critical" />
                    <div className="muted" style={{ marginTop: 6 }}>
                      {trial.no_action.packets_after.toLocaleString()} packets ·{" "}
                      {(trial.no_action.benign_bytes_after / 1_000_000).toFixed(1)} MB benign
                    </div>
                  </div>
                  <div className="trial-arm-wrap">
                    <EventList title="Action continuation (block applied)" events={trial.action_arm.events} tone="good" />
                    <div className="muted" style={{ marginTop: 6 }}>
                      {trial.action_arm.packets_after.toLocaleString()} packets ·{" "}
                      {(trial.action_arm.benign_bytes_after / 1_000_000).toFixed(1)} MB benign ·{" "}
                      {trial.service_disruption.collateral_packets_suppressed} collateral suppressed
                    </div>
                  </div>
                </div>

                <div className="disclosure" role="note" style={{ marginTop: 14, marginBottom: 0 }}>
                  <span className="icon" aria-hidden="true">ⓘ</span>
                  <span>{trial.note}</span>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
