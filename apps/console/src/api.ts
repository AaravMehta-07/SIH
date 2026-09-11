// Typed API client. All failures surface as typed errors; the UI shows
// structured error states instead of inventing values (L.2, UI01).

import type {
  ActionProposalPayload,
  CatalogEntry,
  EvaluationPayload,
  EvidencePayload,
  ForecastPayload,
  HealthPayload,
  QueryAnswerPayload,
  QueryProposalsPayload,
  RevealPayload,
  SessionSummary,
  TaskDef,
} from "./types";

const BASE = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.message) message = body.message;
    } catch {
      /* structured error body absent */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthPayload>("/health"),
  catalog: () => request<{ catalog: CatalogEntry[] }>("/v1/catalog"),
  tasks: () => request<{ tasks: TaskDef[] }>("/v1/tasks"),
  createSession: (catalogId: string) =>
    request<SessionSummary>("/v1/sessions", {
      method: "POST",
      body: JSON.stringify({ catalog_id: catalogId }),
    }),
  session: (sessionId: string) =>
    request<SessionSummary>(`/v1/sessions/${sessionId}`),
  forecast: (sessionId: string, cutoffWindow: number) =>
    request<ForecastPayload>(`/v1/sessions/${sessionId}/forecast`, {
      method: "POST",
      body: JSON.stringify({ cutoff_window: cutoffWindow }),
    }),
  evidence: (sessionId: string, entity: string, taskIndex: number, cutoff?: number) =>
    request<EvidencePayload>(`/v1/sessions/${sessionId}/evidence`, {
      method: "POST",
      body: JSON.stringify({
        entity,
        task_index: taskIndex,
        ...(cutoff != null ? { cutoff_window: cutoff } : {}),
      }),
    }),
  reveal: (sessionId: string, cutoffWindow: number) =>
    request<RevealPayload>(`/v1/sessions/${sessionId}/reveal`, {
      method: "POST",
      body: JSON.stringify({ cutoff_window: cutoffWindow }),
    }),
  evaluation: () => request<EvaluationPayload>("/v1/evaluation"),
  // Tier B (Sections 20-23)
  queryProposals: (sessionId: string, cutoffWindow: number) =>
    request<QueryProposalsPayload>("/v1/queries", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, cutoff_window: cutoffWindow }),
    }),
  queryExecute: (sessionId: string, proposalId: string, cutoffWindow: number) =>
    request<QueryAnswerPayload>(`/v1/queries/${proposalId}/execute`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, cutoff_window: cutoffWindow }),
    }),
  actionPropose: (
    sessionId: string,
    cutoffWindow: number,
    source: string,
    target: string,
  ) =>
    request<ActionProposalPayload>("/v1/actions/propose", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        cutoff_window: cutoffWindow,
        source,
        target,
      }),
    }),
  actionAuthorize: (actionId: string) =>
    request<ActionProposalPayload>(`/v1/actions/${actionId}/authorize`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  actionExecute: (actionId: string, dryRun: boolean) =>
    request<ActionProposalPayload>(`/v1/actions/${actionId}/execute`, {
      method: "POST",
      body: JSON.stringify({ dry_run: dryRun }),
    }),
};
