// FORESIGHT console shell (K.2/K.3). Screens: sessions → forecast →
// evidence → replay → evaluation. The status strip carries the full
// Section-18 axes; the amber disclosure keeps the weights profile explicit
// in every state. Keyboard: 1-5 switch screens when a session is open.

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { StatusStrip } from "./components/StatusStrip";
import { ActionView } from "./views/ActionView";
import { EvaluationView } from "./views/EvaluationView";
import { EvidenceView } from "./views/EvidenceView";
import { ForecastView } from "./views/ForecastView";
import { PathsView } from "./views/PathsView";
import { QueryView } from "./views/QueryView";
import { ReplayView } from "./views/ReplayView";
import { SessionsView } from "./views/SessionsView";
import type {
  CatalogEntry,
  EvaluationPayload,
  ForecastPayload,
  HealthPayload,
  SessionSummary,
} from "./types";

type View =
  | "sessions"
  | "forecast"
  | "evidence"
  | "replay"
  | "evaluation"
  | "paths"
  | "queries"
  | "actions";

const VIEWS: { id: View; label: string; key: string }[] = [
  { id: "sessions", label: "Sessions", key: "1" },
  { id: "forecast", label: "Forecast", key: "2" },
  { id: "evidence", label: "Evidence", key: "3" },
  { id: "replay", label: "Replay", key: "4" },
  { id: "evaluation", label: "Evaluation", key: "5" },
  { id: "paths", label: "Paths", key: "6" },
  { id: "queries", label: "Query", key: "7" },
  { id: "actions", label: "Action", key: "8" },
];

export default function App() {
  const [view, setView] = useState<View>("sessions");
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [session, setSession] = useState<SessionSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastPayload | null>(null);
  const [forecastLoading, setForecastLoading] = useState(false);
  const [forecastError, setForecastError] = useState<string | null>(null);
  const [cutoffWindow, setCutoffWindow] = useState<number>(50);
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationPayload | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalError, setEvalError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api
      .catalog()
      .then((c) => setCatalog(c.catalog))
      .catch(() => setCatalog([]));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      const hit = VIEWS.find((v) => v.key === e.key);
      if (hit && (hit.id === "sessions" || hit.id === "evaluation" || session)) {
        setView(hit.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [session]);

  const refreshForecast = useCallback(
    async (sessionId: string, cutoff: number) => {
      setForecastLoading(true);
      setForecastError(null);
      try {
        const payload = await api.forecast(sessionId, cutoff);
        setForecast(payload);
      } catch (e) {
        setForecastError(String((e as Error).message ?? e));
        setForecast(null);
      } finally {
        setForecastLoading(false);
      }
    },
    [],
  );

  const openSession = useCallback(
    async (catalogId: string) => {
      setOpening(true);
      try {
        const created = await api.createSession(catalogId);
        const detail = await api.session(created.session_id);
        setSessions((prev) => [
          detail,
          ...prev.filter((s) => s.session_id !== detail.session_id),
        ]);
        setSession(detail);
        setSelectedEntity(null);
        const cutoff = detail.valid_cutoffs[Math.floor(detail.valid_cutoffs.length * 0.55)];
        setCutoffWindow(cutoff);
        setView("forecast");
        void refreshForecast(detail.session_id, cutoff);
      } finally {
        setOpening(false);
      }
    },
    [refreshForecast],
  );

  const selectSession = useCallback(
    (s: SessionSummary) => {
      setSession(s);
      setSelectedEntity(null);
      if (!s.valid_cutoffs.includes(cutoffWindow)) {
        const cutoff = s.valid_cutoffs[Math.floor(s.valid_cutoffs.length * 0.55)];
        setCutoffWindow(cutoff);
      }
      setView("forecast");
      void refreshForecast(
        s.session_id,
        s.valid_cutoffs.includes(cutoffWindow)
          ? cutoffWindow
          : s.valid_cutoffs[s.valid_cutoffs.length - 1],
      );
    },
    [cutoffWindow, refreshForecast],
  );

  const changeCutoff = useCallback(
    (cutoff: number) => {
      setCutoffWindow(cutoff);
      if (session) void refreshForecast(session.session_id, cutoff);
    },
    [session, refreshForecast],
  );

  const loadEvaluation = useCallback(() => {
    if (evaluation || evalLoading) return;
    setEvalLoading(true);
    api
      .evaluation()
      .then(setEvaluation)
      .catch((e) => setEvalError(String((e as Error).message ?? e)))
      .finally(() => setEvalLoading(false));
  }, [evaluation, evalLoading]);

  useEffect(() => {
    if (view === "evaluation") loadEvaluation();
  }, [view, loadEvaluation]);

  const disclosure = useMemo(() => {
    const profile = forecast?.weights_profile ?? health?.weights_profile;
    if (!profile) {
      return "Loading model profile…";
    }
    return profile;
  }, [forecast, health]);

  const hasSession = session != null;

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="13.5" fill="none" stroke="#35b8b0" strokeWidth="1.6" opacity="0.85" />
            <circle cx="16" cy="16" r="8.5" fill="none" stroke="#35b8b0" strokeWidth="1.2" opacity="0.5" />
            <circle cx="16" cy="16" r="3.4" fill="#35b8b0" />
            <path d="M16 2.5 A13.5 13.5 0 0 1 29.5 16" fill="none" stroke="#e8edf4" strokeWidth="1.8" strokeLinecap="round" />
            <circle cx="24.5" cy="7.5" r="2.1" fill="#d95926" />
          </svg>
          <span>
            <span className="brand-name">FORESIGHT</span>
            <span className="brand-sub">NETWORK ATTACK FORECASTING · OFFLINE</span>
          </span>
        </div>
        <nav className="nav" aria-label="console screens">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              className={view === v.id ? "active" : ""}
              disabled={!hasSession && v.id !== "sessions" && v.id !== "evaluation"}
              onClick={() => setView(v.id)}
              title={v.id === "sessions" || v.id === "evaluation" || hasSession ? `Screen ${v.key}` : "Open a session first"}
            >
              {v.label}
            </button>
          ))}
        </nav>
        <div className="spacer" />
        <span className="session-chip" title={session ? session.title : "no active session"}>
          {session ? (
            <>
              <b className="mono">{session.session_id}</b>
              <span>· {session.title}</span>
            </>
          ) : (
            "no active session"
          )}
        </span>
        <span
          className={`model-pill ${health?.model_ready ? (health.trained ? "ready" : "untrained") : ""}`}
          title={health?.weights_profile ?? ""}
        >
          <span className="dot" />
          {health ? (health.trained ? "Trained profile" : "Untrained · disclosed") : "…"}
        </span>
      </header>

      <StatusStrip forecast={view === "forecast" || view === "evidence" ? forecast : null} />

      <main className="main">
        <div className="disclosure" role="note">
          <span className="icon" aria-hidden="true">⚠</span>
          <span>
            <b>Demonstration profile.</b> {disclosure} No measured real-world
            performance is claimed (Build Spec Section 29); unsupported targets
            report <span className="mono">not_supported</span>, never zero.
          </span>
        </div>

        {view === "sessions" && (
          <SessionsView
            catalog={catalog}
            sessions={sessions}
            onOpen={openSession}
            onSelect={selectSession}
            loading={opening}
            error={null}
          />
        )}

        {view === "forecast" && session && (
          <ForecastView
            session={session}
            forecast={forecast}
            loading={forecastLoading}
            error={forecastError}
            selectedEntity={selectedEntity ?? forecast?.entities[0]?.name ?? null}
            onSelectEntity={setSelectedEntity}
            cutoffWindow={cutoffWindow}
            onCutoffChange={changeCutoff}
          />
        )}

        {view === "evidence" && session && (
          <EvidenceView
            session={session}
            forecast={forecast}
            selectedEntity={selectedEntity ?? forecast?.entities[0]?.name ?? null}
            onSelectEntity={setSelectedEntity}
            cutoffWindow={cutoffWindow}
          />
        )}

        {view === "replay" && session && (
          <ReplayView
            session={session}
            forecast={forecast}
            cutoffWindow={cutoffWindow}
            onCutoffChange={changeCutoff}
          />
        )}

        {view === "evaluation" && (
          <EvaluationView
            evaluation={evaluation}
            loading={evalLoading}
            error={evalError}
          />
        )}

        {view === "paths" && session && (
          <PathsView
            forecast={forecast}
            loading={forecastLoading}
            error={forecastError}
          />
        )}

        {view === "queries" && session && (
          <QueryView session={session} forecast={forecast} />
        )}

        {view === "actions" && session && (
          <ActionView session={session} forecast={forecast} />
        )}
      </main>
    </>
  );
}
