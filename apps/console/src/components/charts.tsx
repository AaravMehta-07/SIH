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
  series,
  binSeconds,
  horizonMinutes,
  height = 250,
  focusTask,
}: {
  series: TimelineSeries[];
  binSeconds: number;
  horizonMinutes: number;
  height?: number;
  focusTask?: number | null;
}) {
  const [hover, setHover] = useState<{ x: number; bin: number } | null>(null);
  const frameRef = useRef<HTMLDivElement>(null);

  const width = 920;
  const m = { top: 16, right: 118, bottom: 30, left: 46 };
  const iw = width - m.left - m.right;
  const ih = height - m.top - m.bottom;
  const bins = series[0]?.values.length ?? 0;

  const x = (bin: number) => m.left + (bin / Math.max(bins - 1, 1)) * iw;
  const y = (v: number) => m.top + (1 - v) * ih;

  const horizonBins = (horizonMinutes * 60) / binSeconds;

  const onMove = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * width;
    const bin = Math.round(((px - m.left) / iw) * (bins - 1));
    if (bin >= 0 && bin < bins) {
      setHover({ x: px, bin });
    } else {
      setHover(null);
    }
  };

  const yTicks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div ref={frameRef} className="chart-frame">
      {series.length > 1 && (
        <div className="chart-legend" aria-label="series legend">
          {series.map((s) => (
            <span
              key={s.key}
              className={`lg-item ${s.dashed ? "dashed" : ""}`}
              style={{ color: s.color }}
            >
              <span className="swatch" style={{ background: s.dashed ? "transparent" : s.color }} />
              <span style={{ color: "var(--ink-2)" }}>{s.label}</span>
            </span>
          ))}
        </div>
      )}
      <svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: "100%", display: "block" }}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label="cumulative risk over the forecast horizon"
      >
        {/* horizontal grid */}
        {yTicks.map((t) => (
          <g key={t}>
            <line
              x1={m.left}
              x2={width - m.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--grid)"
              strokeWidth={1}
            />
            <text
              x={m.left - 8}
              y={y(t) + 3.5}
              textAnchor="end"
              fontSize={10.5}
              fill="var(--ink-3)"
              fontFamily="var(--mono)"
            >
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}

        {/* published-horizon markers */}
        {[5, 15, 30].map((h) => {
          const bin = (h * 60) / binSeconds - 1;
          if (bin > bins - 1) return null;
          return (
            <g key={h}>
              <line
                x1={x(bin)}
                x2={x(bin)}
                y1={m.top}
                y2={m.top + ih}
                stroke="var(--grid)"
                strokeWidth={1}
                strokeDasharray="2 4"
              />
              <text
                x={x(bin)}
                y={height - 10}
                textAnchor="middle"
                fontSize={10}
                fill="var(--ink-3)"
              >
                {h}m
              </text>
            </g>
          );
        })}
        {/* model-horizon end */}
        <line
          x1={x(bins - 1)}
          x2={x(bins - 1)}
          y1={m.top}
          y2={m.top + ih}
          stroke="var(--border-strong)"
          strokeWidth={1}
        />

        {/* crosshair */}
        {hover && (
          <line
            x1={x(hover.bin)}
            x2={x(hover.bin)}
            y1={m.top}
            y2={m.top + ih}
            stroke="var(--border-strong)"
            strokeWidth={1}
          />
        )}

        {/* series */}
        {(() => {
          // Stagger the direct labels so converging series (e.g. all near
          // 1.0) never stack their end labels on one y (K.3: no overlapping
          // text).
          const endYs = series.map((s) => {
            const clipped = s.values.slice(0, horizonBins);
            return y(clipped[clipped.length - 1] ?? 0);
          });
          const order = endYs
            .map((v, i) => ({ v, i }))
            .sort((a, b) => a.v - b.v);
          const MIN_GAP = 16;
          for (let k = 1; k < order.length; k++) {
            if (order[k].v - order[k - 1].v < MIN_GAP) {
              order[k].v = order[k - 1].v + MIN_GAP;
            }
          }
          const labelY = new Map<number, number>();
          for (const o of order) labelY.set(o.i, o.v);
          return series.map((s) => {
            const clipped = s.values.slice(0, horizonBins);
            const last = clipped.length - 1;
            if (last < 0) return null;
            const path = clipped
              .map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`)
              .join(" ");
            const fp = fingerprint([
              s.key,
              clipped.length,
              clipped[0]?.toFixed(4),
              clipped[last]?.toFixed(4),
              s.threshold,
            ]);
            return (
              <g key={fp}>
                {s.threshold != null && s.threshold > 0 && s.threshold < 1 && (
                  <line
                    className="fade-line"
                    x1={m.left}
                    x2={x(last)}
                    y1={y(s.threshold)}
                    y2={y(s.threshold)}
                    stroke={s.color}
                    strokeWidth={1}
                    strokeDasharray="5 4"
                    opacity={0.55}
                  />
                )}
                <path
                  d={path}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={focusTask != null && focusTask !== Number(s.key) ? 1.25 : 2}
                  strokeDasharray={s.dashed ? "5 4" : undefined}
                  pathLength={s.dashed ? undefined : 1}
                  className={s.dashed ? "fade-line" : "draw-line"}
                  opacity={focusTask != null && focusTask !== Number(s.key) ? 0.38 : 1}
                  strokeLinecap="round"
                />
                <text
                  x={x(last) + 7}
                  y={(labelY.get(series.indexOf(s)) ?? y(clipped[last])) + 3.5}
                  fontSize={10.5}
                  fill="var(--ink-2)"
                >
                  {s.label}
                </text>
                {hover && (
                  <circle
                    cx={x(Math.min(hover.bin, last))}
                    cy={y(clipped[Math.min(hover.bin, last)])}
                    r={3.5}
                    fill={s.color}
                    stroke="var(--chart)"
                    strokeWidth={1.5}
                  />
                )}
              </g>
            );
          });
        })()}
      </svg>

      {hover && (
        <div
          className="chart-tooltip"
          style={{
            left: Math.min(
              (hover.x / width) * (frameRef.current?.clientWidth ?? 0) + 18,
              (frameRef.current?.clientWidth ?? 400) - 190,
            ),
            top: 12,
          }}
        >
          <div className="tt-title">
            +{((hover.bin + 1) * binSeconds) / 60 >= 1
              ? `${Math.round(((hover.bin + 1) * binSeconds) / 60)} min`
              : `${(hover.bin + 1) * binSeconds}s`}{" "}
            after cutoff
          </div>
          {series
            .slice()
            .sort(
              (a, b) =>
                (b.values[Math.min(hover.bin, b.values.length - 1)] ?? 0) -
                (a.values[Math.min(hover.bin, a.values.length - 1)] ?? 0),
            )
            .map((s) => (
              <div className="tt-row" key={s.key}>
                <span className="swatch" style={{ background: s.color }} />
                <span>{s.label}</span>
                <span className="tt-val">
                  {pct(s.values[Math.min(hover.bin, s.values.length - 1)])}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
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
