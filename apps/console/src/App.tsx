// FORESIGHT console shell (K.2/K.3). Screens: sessions → forecast →
// evidence → replay → evaluation. The status strip carries the full
// Section-18 axes; the amber disclosure keeps the weights profile explicit
// in every state. Keyboard: 1-5 switch screens when a session is open.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, Boxes, ChartNoAxesCombined, Fingerprint, GitBranch, History, ShieldCheck, ChevronDown, Radio } from "lucide-react";
import { api } from "./api";
import { StatusStrip } from "./components/StatusStrip";
import { EvaluationView } from "./views/EvaluationView";
import { EvidenceView } from "./views/EvidenceView";
import { ForecastView } from "./views/ForecastView";
import { PathsView } from "./views/PathsView";
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
  | "paths"
  | "replay"
  | "evaluation";

const VIEWS: { id: View; label: string; key: string }[] = [
  { id: "sessions", label: "Sessions", key: "1" },
  { id: "forecast", label: "Forecast", key: "2" },
  { id: "evidence", label: "Evidence", key: "3" },
  { id: "paths", label: "Paths", key: "4" },
  { id: "replay", label: "Replay", key: "5" },
  { id: "evaluation", label: "Evaluation", key: "6" },
];
const VIEW_ICONS = [Boxes, Activity, Fingerprint, GitBranch, History, ChartNoAxesCombined];

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
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const forecastRequest = useRef(0);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api
      .catalog()
      .then((c) => setCatalog(c.catalog))
      .catch((e) => setSessionError(e.message))
      .finally(() => setCatalogLoading(false));
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey || e.ctrlKey || e.metaKey || e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement || e.target instanceof HTMLTextAreaElement || (e.target instanceof HTMLElement && e.target.isContentEditable)) return;
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
      const requestId = ++forecastRequest.current;
      setForecastLoading(true);
      setForecast(null);
      setForecastError(null);
      try {
        const payload = await api.forecast(sessionId, cutoff);
        if (requestId !== forecastRequest.current) return;
        setForecast(payload);
      } catch (e) {
        if (requestId !== forecastRequest.current) return;
        setForecastError(String((e as Error).message ?? e));
        setForecast(null);
      } finally {
        if (requestId === forecastRequest.current) setForecastLoading(false);
      }
    },
    [],
  );

  const openSession = useCallback(
    async (catalogId: string) => {
      setOpening(true);
      setSessionError(null);
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
      } catch (e) {
        setSessionError((e as Error).message);
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
      const cutoff = s.valid_cutoffs.includes(cutoffWindow) ? cutoffWindow : s.valid_cutoffs[Math.floor(s.valid_cutoffs.length * 0.55)];
      setCutoffWindow(cutoff);
      setView("forecast");
      void refreshForecast(
        s.session_id,
        cutoff,
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
    if (evaluation || evalLoading || evalError) return;
    setEvalLoading(true);
    api
      .evaluation()
      .then(setEvaluation)
      .catch((e) => setEvalError(String((e as Error).message ?? e)))
      .finally(() => setEvalLoading(false));
  }, [evaluation, evalLoading, evalError]);

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
          <ShieldCheck className="brand-mark" aria-hidden="true" />
          <span>
            <span className="brand-name">FORESIGHT</span>
            <span className="brand-sub">Network intelligence</span>
          </span>
        </div>
        <nav className="nav" aria-label="console screens">
          {VIEWS.map((v, i) => {
            const Icon = VIEW_ICONS[i];
            return (
            <button
              key={v.id}
              className={view === v.id ? "active" : ""}
              disabled={!hasSession && v.id !== "sessions" && v.id !== "evaluation"}
              onClick={() => setView(v.id)}
              aria-current={view === v.id ? "page" : undefined}
              title={v.id === "sessions" || v.id === "evaluation" || hasSession ? `Screen ${v.key}` : "Open a session first"}
            >
              <Icon size={18} aria-hidden="true" /><span>{v.label}</span>
            </button>
          );})}
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
          {health ? (!health.model_ready ? "Model unavailable" : health.trained ? "Trained profile" : "Untrained · disclosed") : "Connecting"}
        </span>
        <div className="rail-footer"><Radio size={14} /> Local workspace <span>SIH26153 / Deja Vu T-1</span></div>
      </header>

      <StatusStrip forecast={forecast} />

      <main className="main">
        <details className="disclosure">
          <summary><ShieldCheck size={15} /><b>Evidence-accountable forecasting</b><span>{session?.synthetic === false ? "Real capture" : "Disclosed demonstration"} · Offline</span><ChevronDown size={14} /></summary>
          <div className="disclosure-content">
            <b>Demonstration profile.</b> {disclosure} No measured real-world
            performance is claimed (Build Spec Section 29); unsupported targets
            report <span className="mono">not_supported</span>, never zero.
            {session?.data_disclosure ? <> <b>Active source:</b> {session.data_disclosure}</> : null}
          </div>
        </details>

        {view === "sessions" && (
          <SessionsView
            catalog={catalog}
            sessions={sessions}
            onOpen={openSession}
            onSelect={selectSession}
            loading={opening || catalogLoading}
            error={sessionError}
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
            key={`${session.session_id}:${cutoffWindow}`}
            session={session}
            forecast={forecast}
            selectedEntity={selectedEntity ?? forecast?.entities[0]?.name ?? null}
            onSelectEntity={setSelectedEntity}
            cutoffWindow={cutoffWindow}
          />
        )}

        {view === "replay" && session && (
          <ReplayView
            key={`${session.session_id}:${cutoffWindow}`}
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
      </main>
    </>
  );
}
