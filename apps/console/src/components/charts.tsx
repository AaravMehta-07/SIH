// Shared UI atoms + SVG chart components. Charts follow the dataviz
// method: one axis, thin marks, crosshair tooltips on time series,
// direct labels selectively, text in ink tokens (never series hue).

import { useEffect, useRef, useState } from "react";
import type { EntityForecast, TaskForecast } from "../types";
import { TASK_COLORS, TASKS } from "../types";

/* ------------------------------------------------------------------ */
/* Motion hooks                                                        */
/* ------------------------------------------------------------------ */

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

/** Animated number: rAF count-up on mount and on value change. */
export function useCountUp(value: number, durationMs = 650): number {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const rafRef = useRef(0);

  useEffect(() => {
    if (prefersReducedMotion()) {
      fromRef.current = value;
      setDisplay(value);
      return;
    }
    const from = fromRef.current;
    if (from === value) return;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min((now - start) / durationMs, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (value - from) * eased);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = value;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value, durationMs]);

  return display;
}

/** Fingerprint for chart elements: changing it remounts the element, which
 * replays its entrance animation when the data changes. */
function fingerprint(parts: (string | number | undefined | null)[]): string {
  return parts.map((p) => String(p ?? "")).join("|");
}

/* ------------------------------------------------------------------ */
/* Status + layout atoms                                               */
/* ------------------------------------------------------------------ */

export function Spinner() {
  return <div className="spinner" aria-label="loading" />;
}

export function LoadingPanel({ label }: { label: string }) {
  return (
    <div className="loading-panel">
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="error-panel" role="alert">
      <span aria-hidden="true">⚠</span>
      <span>
        <b>Request failed.</b> {message}
      </span>
    </div>
  );
}

export function Skeleton({ height }: { height: number }) {
  return <div className="skeleton" style={{ height }} />;
}

export function Tile({
  label,
  value,
  suffix,
  foot,
  tone = "",
}: {
  label: string;
  value: string;
  suffix?: string;
  foot?: string;
  tone?: "good" | "warn" | "serious" | "critical" | "accent" | "";
}) {
  return (
    <div className={`tile ${tone}`}>
      <div className="label">{label}</div>
      <div className="value">
        {value}
        {suffix ? <small>{suffix}</small> : null}
      </div>
      {foot ? <div className="foot">{foot}</div> : null}
    </div>
  );
}

export function riskLevel(p: number | null): string {
  if (p == null) return "na";
  if (p >= 0.6) return "l4";
  if (p >= 0.3) return "l3";
  if (p >= 0.1) return "l2";
  if (p >= 0.02) return "l1";
  return "l0";
}

export function pct(p: number | null | undefined, digits = 1): string {
  if (p == null) return "—";
  return `${(p * 100).toFixed(digits)}%`;
}

export function taskColor(index: number): string {
  return TASK_COLORS[index % TASK_COLORS.length];
}

/* ------------------------------------------------------------------ */
/* Cumulative-risk timeline                                            */
/* ------------------------------------------------------------------ */

export interface TimelineSeries {
  key: string;
  label: string;
  color: string;
  values: number[];
  threshold: number | null;
  dashed?: boolean;
}

export function RiskTimeline({
  series, binSeconds, horizonMinutes, height = 250, focusTask,
}: {
  series: TimelineSeries[]; binSeconds: number; horizonMinutes: number;
  height?: number; focusTask?: number | null;
}) {
  const [hoverBin, setHoverBin] = useState<number | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [width, setWidth] = useState(320);
  const frameRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, entry.contentRect.width)));
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);
  const bins = Math.min(Math.floor(horizonMinutes * 60 / binSeconds), ...series.map(s => s.values.length));
  const m = { top: 14, right: 14, bottom: 29, left: 35 };
  const iw = width - m.left - m.right, ih = height - m.top - m.bottom;
  const maximum = Math.max(0.01, ...series.flatMap(s => s.values.slice(0, bins)));
  const ceiling = maximum <= .05 ? .05 : maximum <= .1 ? .1 : maximum <= .25 ? .25 : maximum <= .5 ? .5 : 1;
  const x = (bin: number) => m.left + ((bin + 1) / Math.max(bins, 1)) * iw;
  const y = (value: number) => m.top + (1 - value / ceiling) * ih;
  const selected = active ?? (focusTask != null ? String(focusTask) : null);
  const probe = hoverBin == null ? bins - 1 : Math.min(hoverBin, bins - 1);
  return <div ref={frameRef} className="chart-frame risk-timeline">
    <div className="chart-legend" aria-label="series legend">
      {series.map(s => <button key={s.key} className="lg-item" aria-pressed={active === s.key}
        onClick={() => setActive(active === s.key ? null : s.key)} title={`Highlight ${s.label}`}>
        <span className="swatch" style={{ background: s.color }} />
        <span>{s.label}</span><b>{pct(s.values[probe])}</b>
      </button>)}
    </div>
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", display: "block" }}
      role="slider" tabIndex={0} aria-label="Forecast time, use arrow keys to inspect risk"
      aria-valuemin={binSeconds} aria-valuemax={bins * binSeconds} aria-valuenow={(probe + 1) * binSeconds}
      aria-valuetext={`${(probe + 1) * binSeconds} seconds after cutoff: ${series.map(s => `${s.label} ${pct(s.values[probe])}`).join(", ")}`}
      onKeyDown={e => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); setHoverBin(Math.max(0, Math.min(bins - 1, probe + (e.key === "ArrowLeft" ? -1 : 1)))); } }}
      onMouseMove={e => { const box = e.currentTarget.getBoundingClientRect(); const px = (e.clientX - box.left) / box.width * width; setHoverBin(Math.max(0, Math.min(bins - 1, Math.round((px - m.left) / iw * bins) - 1))); }}
      onMouseLeave={() => setHoverBin(null)} onBlur={() => setHoverBin(null)}>
      {[0, .25, .5, .75, 1].map(f => <g key={f}>
        <line x1={m.left} x2={width-m.right} y1={y(f*ceiling)} y2={y(f*ceiling)} stroke="var(--grid)" strokeDasharray={f ? "2 3" : undefined} />
        <text x={m.left-6} y={y(f*ceiling)+3} textAnchor="end" fontSize={9} fill="var(--ink-3)">{+(f*ceiling*100).toFixed(2)}%</text>
      </g>)}
      {[0, .5, 1].map(f => <text key={f} x={m.left+f*iw} y={height-8} textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} fontSize={9} fill="var(--ink-3)">{+(f*bins*binSeconds/60).toFixed(1)}m</text>)}
      {series.map(s => {
        const values = s.values.slice(0,bins);
        const d = values.map((v,i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
        return <path key={fingerprint([s.key, bins, values[0], values[values.length-1]])} d={d} fill="none"
          stroke={s.color} strokeWidth={selected === s.key ? 2.5 : 1.7} opacity={selected && selected !== s.key ? .18 : 1}
          strokeLinecap="round" pathLength={1} className="draw-line"><title>{s.label}: {pct(values[values.length-1])}</title></path>;
      })}
      {hoverBin != null && <g>
        <line x1={x(probe)} x2={x(probe)} y1={m.top} y2={height-m.bottom} stroke="var(--ink-3)" strokeDasharray="3 3" />
        {series.map(s => <circle key={s.key} cx={x(probe)} cy={y(s.values[probe])} r={3} fill={s.color} stroke="var(--panel)" strokeWidth={1.5} />)}
      </g>}
    </svg>
    <div className="chart-readout">{hoverBin == null ? `Cumulative probability · ${horizonMinutes}-minute horizon` : `At +${(probe+1)*binSeconds} seconds · backend forecast`}</div>
  </div>;
}

/* ------------------------------------------------------------------ */
/* Reliability diagram (evaluation view)                               */
/* ------------------------------------------------------------------ */

export function ReliabilityChart({
  bins,
  height = 240,
}: {
  bins: { bin_lower: number; bin_upper: number; count: number; mean_forecast: number | null; observed_rate: number | null }[];
  height?: number;
}) {
  const width = 420;
  const m = { top: 14, right: 14, bottom: 32, left: 40 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const x = (v: number) => m.left + v * iw;
  const y = (v: number) => m.top + (1 - v) * ih;

  const points = bins.filter((b) => b.count > 0 && b.mean_forecast != null);
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(p.mean_forecast!).toFixed(1)},${y(p.observed_rate!).toFixed(1)}`)
    .join(" ");

  return (
    <div className="chart-frame">
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", display: "block" }} role="img"
        aria-label="reliability diagram, forecast versus observed rate">
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line x1={m.left} x2={width - m.right} y1={y(t)} y2={y(t)} stroke="var(--grid)" />
            <line y1={m.top} y2={m.top + ih} x1={x(t)} x2={x(t)} stroke="var(--grid)" />
          </g>
        ))}
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          stroke="var(--ink-3)"
          strokeDasharray="4 4"
          strokeWidth={1}
        />
        {path && (
          <path
            d={path}
            fill="none"
            stroke="var(--task-0)"
            strokeWidth={2}
            strokeLinecap="round"
            pathLength={1}
            className="draw-line"
          />
        )}
        {points.map((p, i) => (
          <circle
            key={i}
            className="pop-in"
            style={{ animationDelay: `${200 + i * 40}ms` }}
            cx={x(p.mean_forecast!)}
            cy={y(p.observed_rate!)}
            r={Math.min(4 + Math.sqrt(p.count) * 0.9, 11)}
            fill="var(--task-0)"
            fillOpacity={0.28}
            stroke="var(--task-0)"
            strokeWidth={1.4}
          />
        ))}
        <text x={x(0.5)} y={height - 10} textAnchor="middle" fontSize={10.5} fill="var(--ink-3)">
          forecast cumulative risk →
        </text>
        <text
          x={12}
          y={m.top + ih / 2}
          fontSize={10.5}
          fill="var(--ink-3)"
          transform={`rotate(-90 12 ${m.top + ih / 2})`}
          textAnchor="middle"
        >
          observed rate
        </text>
        <text x={x(0.94)} y={y(0.8)} fontSize={9.5} fill="var(--ink-3)">
          perfect
        </text>
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Attribution bars (diverging: support vs suppressive)                */
/* ------------------------------------------------------------------ */

export function AttributionBars({
  items,
  baseline,
}: {
  items: { window_index: number; delta: number; category: string }[];
  baseline: number;
}) {
  const width = 640;
  const rowH = 22;
  const labelW = 74;
  const height = items.length * rowH + 34;
  const maxAbs = Math.max(baseline * 0.4, ...items.map((i) => Math.abs(i.delta)), 0.001);
  const zeroX = labelW + (width - labelW - 12) * 0.62;
  const scale = (v: number) => (v / maxAbs) * (width - labelW - 24) * 0.36;

  return (
    <div className="chart-frame">
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", display: "block" }} role="img"
        aria-label="deletion attribution deltas by prefix window">
        <line x1={zeroX} x2={zeroX} y1={8} y2={height - 26} stroke="var(--border-strong)" />
        {items.map((item, i) => {
          const y = 10 + i * rowH;
          const w = Math.abs(scale(item.delta));
          const supporting = item.delta > 0;
          return (
            <g key={fingerprint([i, item.window_index, item.delta.toFixed(4)])}>
              <text x={labelW - 8} y={y + 12} fontSize={10.5} fill="var(--ink-3)" textAnchor="end"
                fontFamily="var(--mono)">
                w{item.window_index}
              </text>
              <rect
                className={supporting ? "grow-l" : "grow-r"}
                style={{ animationDelay: `${i * 35}ms` }}
                x={supporting ? zeroX : zeroX - w}
                y={y + 3}
                width={w}
                height={12}
                rx={2.5}
                fill={supporting ? "var(--critical)" : "var(--task-0)"}
                opacity={supporting ? 0.85 : 0.6}
              />
              <text
                x={supporting ? zeroX + w + 6 : zeroX - w - 6}
                y={y + 12.5}
                fontSize={10}
                fill="var(--ink-2)"
                textAnchor={supporting ? "start" : "end"}
                fontFamily="var(--mono)"
              >
                {item.delta >= 0 ? "+" : ""}
                {(item.delta * 100).toFixed(1)}pp
              </text>
            </g>
          );
        })}
        <text x={zeroX + 6} y={height - 10} fontSize={10} fill="var(--ink-3)">
          risk dropped when deleted (supporting evidence) →
        </text>
        <text x={zeroX - 6} y={height - 10} fontSize={10} fill="var(--ink-3)" textAnchor="end">
          ← suppressive
        </text>
      </svg>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Horizontal per-task AP bars                                         */
/* ------------------------------------------------------------------ */

export function TaskBars({
  values,
}: {
  values: { task: number; label: string; value: number | null }[];
}) {
  return (
    <div style={{ display: "grid", gap: 8, padding: "4px 2px" }}>
      {values.map((v) => (
        <div key={v.task} style={{ display: "grid", gridTemplateColumns: "150px 1fr 52px", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: "var(--ink-2)", display: "flex", alignItems: "center", gap: 7 }}>
            <span className="swatch" style={{ width: 9, height: 9, borderRadius: 3, background: taskColor(v.task), display: "inline-block" }} />
            {v.label}
          </span>
          <div style={{ height: 9, background: "var(--chart)", borderRadius: 5, overflow: "hidden", border: "1px solid var(--border)" }}>
            {v.value != null && (
              <div
                key={v.value.toFixed(4)}
                className="meter-fill"
                style={
                  {
                    "--w": `${Math.max(v.value * 100, 1.5)}%`,
                    height: "100%",
                    background: taskColor(v.task),
                    opacity: 0.85,
                    borderRadius: 5,
                  } as React.CSSProperties
                }
              />
            )}
          </div>
          <span className="mono" style={{ fontSize: 11.5, color: "var(--ink-2)", textAlign: "right" }}>
            {v.value == null ? "—" : v.value.toFixed(3)}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Entity × task risk matrix row helper                                */
/* ------------------------------------------------------------------ */

export function entityMaxOccurrence(entity: EntityForecast, bins: number): number {
  let max = 0;
  for (const t of entity.tasks) {
    if (t.cumulative_risk) {
      max = Math.max(max, t.cumulative_risk[Math.min(bins, t.cumulative_risk.length) - 1]);
    }
  }
  return max;
}

export function taskAt(entity: EntityForecast, index: number): TaskForecast {
  return entity.tasks.find((t) => t.task_index === index)!;
}

export const TASK_LABELS = TASKS.map((t) => t.label);
