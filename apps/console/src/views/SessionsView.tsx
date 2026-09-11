// Sessions screen (K.2): operational file/session view — catalog of capture
// sessions, source format, capabilities, parse status. Not promotional.

import { useState } from "react";
import type { CatalogEntry, SessionSummary } from "../types";
import { ErrorPanel, LoadingPanel } from "../components/charts";

const FAMILY_LABEL: Record<string, string> = {
  "benign-baseline": "benign",
  "benign-drift": "benign drift",
  "web-to-lateral": "attack · web → lateral",
  "c2-exfil": "attack · C2 → exfil",
  "slow-recon": "attack · slow recon",
  "cred-spray": "attack · credential spray",
};

export function SessionsView({
  catalog,
  sessions,
  onOpen,
  onSelect,
  loading,
  error,
}: {
  catalog: CatalogEntry[];
  sessions: SessionSummary[];
  onOpen: (catalogId: string) => void;
  onSelect: (session: SessionSummary) => void;
  loading: boolean;
  error: string | null;
}) {
  const [opening, setOpening] = useState<string | null>(null);

  const open = async (catalogId: string) => {
    setOpening(catalogId);
    try {
      await onOpen(catalogId);
    } finally {
      setOpening(null);
    }
  };

  return (
    <div className="fade-in">
      <div className="view-header">
        <div>
          <h1>Capture sessions</h1>
          <p className="sub">
            Offline capture replays through the Section-26 pipeline. Each source
            discloses which flow and packet measurements are actually available.
          </p>
        </div>
      </div>

      {error && <ErrorPanel message={error} />}

      <div className="catalog">
        {catalog.map((entry) => {
          const attack = entry.campaign.startsWith("web") || entry.campaign.startsWith("c2")
            || entry.campaign.startsWith("slow") || entry.campaign.startsWith("cred");
          return (
            <div className="catalog-card" key={entry.catalog_id}>
              <div className="card-meta">
                <span className={`tag ${attack ? "attack" : "benign"}`}>
                  {FAMILY_LABEL[entry.campaign] ?? entry.campaign}
                </span>
                <span className={`tag ${entry.synthetic ? "synth" : "benign"}`}>
                  {entry.synthetic ? "synthetic · disclosed" : "real capture · disclosed"}
                </span>
              </div>
              <h3>{entry.title}</h3>
              <p>{entry.summary}</p>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span className="muted">{entry.source_format}</span>
                <button
                  className="btn primary small"
                  onClick={() => open(entry.catalog_id)}
                  disabled={entry.available === false || opening === entry.catalog_id || loading}
                >
                  {entry.available === false
                    ? "Dataset not installed"
                    : opening === entry.catalog_id ? "Opening…" : "Open session"}
                </button>
              </div>
            </div>
          );
        })}
        {catalog.length === 0 && !loading && (
          <div className="panel" style={{ gridColumn: "1/-1" }}>
            <div className="empty-state">
              <span className="glyph">◍</span>
              No captures available — is the API running?
            </div>
          </div>
        )}
        {loading && catalog.length === 0 && (
          <div className="panel" style={{ gridColumn: "1/-1" }}>
            <LoadingPanel label="Loading capture catalog…" />
          </div>
        )}
      </div>

      {sessions.length > 0 && (
        <>
          <div className="section-label">Open sessions</div>
          <div className="panel">
            <div className="panel-head">
              <h2>Active</h2>
              <span className="hint">
                forecast · evidence · replay are available per session
              </span>
            </div>
            <div className="panel-body flush table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Session</th>
                    <th>Capture</th>
                    <th>Family</th>
                    <th className="num">Entities</th>
                    <th className="num">Cutoffs</th>
                    <th>Parse status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={s.session_id}>
                      <td className="mono">{s.session_id}</td>
                      <td>{s.title}</td>
                      <td>
                        <span className={`tag ${s.campaign.includes("benign") ? "benign" : "attack"}`}>
                          {FAMILY_LABEL[s.campaign] ?? s.campaign}
                        </span>
                      </td>
                      <td className="num">{s.entity_count}</td>
                      <td className="num">{s.valid_cutoffs.length}</td>
                      <td>{s.parse_status ?? "qualified"}</td>
                      <td>
                        <button
                          className="btn ghost small"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelect(s);
                          }}
                        >
                          Forecast →
                        </button>
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
