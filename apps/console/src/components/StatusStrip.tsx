// Section-18 orthogonal state axes (full fidelity with compatibility labels).
// Missing data can coexist with elevated risk; no axis collapses into another.

import type { ForecastPayload } from "../types";

export function StatusStrip({ forecast }: { forecast: ForecastPayload | null }) {
  const axes = deriveAxes(forecast);
  return (
    <div className="status-strip" role="status" aria-label="operational state axes">
      {axes.map((a) => (
        <div key={a.name} className={`axis-chip ${a.tone}`} title={a.detail}>
          <span className="axis">{a.name}</span>
          <span className="value">
            {a.value}
            {a.compat ? <span className="compat">{a.compat}</span> : null}
          </span>
        </div>
      ))}
    </div>
  );
}

interface Axis {
  name: string;
  value: string;
  compat?: string;
  tone: string;
  detail: string;
}

function deriveAxes(forecast: ForecastPayload | null): Axis[] {
  if (!forecast) {
    return [
      { name: "Forecast support", value: "no session", tone: "dim", detail: "Open a capture session to forecast" },
      { name: "Threat evidence", value: "—", tone: "dim", detail: "" },
      { name: "Novelty", value: "—", tone: "dim", detail: "" },
      { name: "Health", value: "—", tone: "dim", detail: "" },
      { name: "Action authority", value: "observe", compat: "· disabled", tone: "dim", detail: "Offline core profile: forecasts and evidence only (Section 23)" },
    ];
  }

  const alerting = forecast.entities.some((e) => e.tasks.some((t) => t.alerting));
  const supported = forecast.entities.some((e) =>
    e.tasks.some((t) => t.status === "supported"),
  );
  const noveltyStatus = forecast.novelty.status;
  const health = forecast.coverage.health;
  const gaps = forecast.coverage.sensor_gaps.length;

  return [
    {
      name: "Forecast support",
      value: supported ? "supported" : "abstained",
      compat: supported ? `· ${new Set(forecast.entities.flatMap(e => e.tasks.filter(t => t.status === "supported").map(t => t.task_index))).size} targets` : "",
      tone: supported ? "ok" : "warn",
      detail: "Whether the stated task can be published (Section 18)",
    },
    {
      name: "Threat evidence",
      value: alerting ? "elevated" : supported ? "low" : "unavailable",
      compat: alerting ? "· alerting" : "",
      tone: alerting ? "alert" : "ok",
      detail:
        "Assessment under available evidence; not hidden-state certainty",
    },
    {
      name: "Novelty",
      value:
        noveltyStatus === "novel"
          ? "novel"
          : noveltyStatus === "reference_like"
            ? "reference-like"
            : "unavailable",
      compat:
        forecast.novelty.max_residual_score != null
          ? `· ${forecast.novelty.max_residual_score.toFixed(1)}σ`
          : "",
      tone: noveltyStatus === "novel" ? "novel" : noveltyStatus === "reference_like" ? "ok" : "dim",
      detail: forecast.novelty.note,
    },
    {
      name: "Health",
      value: health,
      compat: gaps ? `· ${gaps} gap${gaps > 1 ? "s" : ""}` : "",
      tone: gaps ? "warn" : "ok",
      detail: "Input/model/runtime health; missing data coexists with risk",
    },
    {
      name: "Action authority",
      value: "observe",
      compat: "· disabled",
      tone: "dim",
      detail: "No forecast-to-actuator shortcut (Section 3)",
    },
  ];
}
