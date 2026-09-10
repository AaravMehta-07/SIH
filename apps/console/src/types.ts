// FORESIGHT console API types (Appendix L.2 / D.7 semantics).
// The UI renders these values; it never recomputes probabilities
// frontend-side (K.2).

export interface HealthPayload {
  status: string;
  model_ready: boolean;
  trained: boolean;
  schema: string;
  weights_profile: string;
  sessions: number;
  action_mode: string;
  offline: boolean;
}

export interface CatalogEntry {
  catalog_id: string;
  campaign: string;
  title: string;
  summary: string;
  family: string;
  synthetic: boolean;
  source_format: string;
}

export interface TaskDef {
  task_index: number;
  id: string;
  label: string;
  label_tier: string;
  description: string;
}

export interface SessionSummary {
  session_id: string;
  episode_id: string;
  campaign: string;
  title: string;
  summary: string;
  created_at: number;
  cutoff_window: number;
  valid_cutoffs: number[];
  entity_count: number;
  synthetic: boolean;
  weights_profile: string;
  history_windows?: number;
  parse_status?: string;
  packet_count?: number;
  capabilities?: Record<string, unknown>;
  observation_gaps?: { host: string; from_ns: string; to_ns: string }[];
}

export interface ConditionalEta {
  median_bin: number;
  median_seconds: number;
  occurrence_probability: number;
  bin_seconds: number;
  condition: string;
}

export interface TaskForecast {
  task_index: number;
  task_id: string;
  task_label: string;
  label_tier: string;
  status: string;
  calibration_status: string;
  cumulative_risk: number[] | null;
  event_mass: number[] | null;
  no_event_mass: number | null;
  occurrence_probability: number | null;
  eta: ConditionalEta | null;
  eta_withheld_reason: string | null;
  disagreement: number | null;
  policy_threshold: number | null;
  alerting: boolean;
  trust: { status: string; calibration: string };
}

export interface TacticTag {
  tactic: string;
  probability: number;
}

export interface EntityForecast {
  slot: number;
  name: string;
  role: string;
  tasks: TaskForecast[];
  tactic_tags: TacticTag[];
}

export interface GraphNode {
  slot: number;
  name: string;
  role: string;
  x: number;
  y: number;
}

export interface ObservedEdge {
  source: string;
  target: string;
  windows: number[];
  first_window: number;
  last_window: number;
}

export interface CandidateEdge {
  source: string;
  target: string;
  probability: number;
}

export interface NoveltyEntity {
  status: string;
  residual_score: number | null;
  embedding_distance: number | null;
  contributing_groups: string[];
  per_group: Record<string, number>;
  note: string;
}

export interface ForecastPayload {
  weights_profile: string;
  model: {
    kind: string;
    members: number;
    seeds: number[];
    params_per_member: number;
    trained: boolean;
  };
  horizon_bins: number;
  bin_seconds: number;
  published_horizons_seconds: number[];
  cutoff_window: number;
  cutoff_seconds: number;
  compute_seconds: number;
  display_eta_threshold: number;
  entities: EntityForecast[];
  graph: { nodes: GraphNode[]; observed_edges: ObservedEdge[] };
  novelty: {
    status: string;
    max_residual_score: number | null;
    per_entity: Record<string, NoveltyEntity>;
    note: string;
  };
  flagged: { window: number; kind: string; entity: string; reason: string }[];
  coverage: {
    history_windows: number;
    window_count: number;
    health: string;
    sensor_gaps: { host: string; from_window: number; to_window: number }[];
    observed_hosts: number;
  };
  paths: { status: string; note: string; candidate_edges: CandidateEdge[] };
  record: {
    forecast_id: string;
    forecast_hash: string;
    committed: boolean;
    published_at_ns: string;
    compute_to_ledger_seconds: number;
  };
}

export interface EvidenceItem {
  category: string;
  entity: string;
  window_index: number;
  delta: number;
  packet_row_count: number;
  method: string;
}

export interface EvidencePayload {
  entity: string;
  task_index: number;
  horizon_bins: number;
  baseline_risk: number;
  evidence: EvidenceItem[];
  comprehensiveness: number | null;
  sufficiency: number | null;
  random_baseline_comprehensiveness: number | null;
  partial: boolean;
  note: string;
  flows: {
    window: number;
    source: string;
    target: string;
    dport: number;
    protocol: string;
    bytes: number;
    at_ns: string;
  }[];
  weights_profile: string;
}

export interface RevealEvent {
  entity: string;
  task_index: number;
  task_id: string;
  task_label: string;
  label_tier: string;
  event_window: number;
  relative_to_cutoff: number;
  status: string;
}

export interface RevealPayload {
  cutoff_window: number;
  weights_profile: string;
  note: string;
  events: RevealEvent[];
  forecast_comparison:
    | {
        entity: string;
        task_index: number;
        outcome: string;
        lead_seconds: number | null;
      }[]
    | null;
}

export interface GateRow {
  name: string;
  status: string;
  value: number | null;
  threshold: number | null;
  reason: string;
}

export interface EvaluationPayload {
  weights_profile: string;
  trained: boolean;
  golden_example_1: {
    cumulative_matches: boolean;
    no_event_matches: boolean;
    conditional_median_bin: number | null;
    expected_median_bin: number;
    cumulative_risk: number[];
    expected_cumulative_risk: number[];
  };
  locked_test_report:
    | {
        gates: GateRow[];
        metrics: {
          precision: number;
          event_recall: number;
          f1: number;
          false_alerts_per_100_asset_hours: number;
          asset_hours: number;
          matched_events: number;
          missed_events: number;
          unmatched_alerts: number;
          average_precision_primary: number;
          brier_300s: number;
          brier_n: number;
          ece_300s: number;
          reliability_300s: {
            bins: {
              bin_lower: number;
              bin_upper: number;
              count: number;
              mean_forecast: number | null;
              observed_rate: number | null;
            }[];
          };
          lead_time_seconds_median: number | null;
          event_recall_bootstrap: {
            mean: number | null;
            ci_low: number | null;
            ci_high: number | null;
            units: number;
          };
        };
        baselines: Record<string, number | string>;
        per_task: Record<
          string,
          { records?: number; primary_horizon_events?: number; ap?: number; status?: string }
        >;
        per_family: Record<
          string,
          { prediction_records: number; primary_horizon_events: number }
        >;
        note: string;
      }
    | null;
  note: string;
}

export const TASKS = [
  { index: 0, id: "malicious-endpoint-contact", label: "Endpoint contact", tier: "proxy" },
  { index: 1, id: "initial-access", label: "Initial access", tier: "confirmed" },
  { index: 2, id: "lateral-movement", label: "Lateral movement", tier: "confirmed" },
  { index: 3, id: "command-and-control", label: "Command & control", tier: "confirmed" },
  { index: 4, id: "exfiltration", label: "Exfiltration", tier: "confirmed" },
] as const;

export const TACTICS = [
  "reconnaissance",
  "initial-access",
  "lateral-movement",
  "command-and-control",
  "exfiltration",
] as const;

export const TASK_COLORS = [
  "#3987e5",
  "#d95926",
  "#199e70",
  "#c98500",
  "#d55181",
] as const;
