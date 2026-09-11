// Observed-communication graph (K.2): role-colored nodes, observed edges
// solid with recency opacity, predicted candidate edges dashed and clearly
// legend-separated — no predicted edge is rendered as confirmed traffic.

import { useState } from "react";
import type { CandidateEdge, GraphNode, ObservedEdge } from "../types";

const ROLE_COLORS: Record<string, string> = {
  workstation: "#5f8fd9",
  "app-server": "#7e6fd0",
  database: "#c98500",
  "domain-controller": "#c25cc9",
  "file-server": "#4fae9b",
  proxy: "#6f8296",
  "web-server": "#d95926",
  backup: "#8a9280",
  security: "#3fc3c0",
};

export function GraphView({
  nodes,
  observedEdges,
  predictedEdges,
  cutoffWindow,
  selectedEntity,
  onSelectEntity,
}: {
  nodes: GraphNode[];
  observedEdges: ObservedEdge[];
  predictedEdges: CandidateEdge[];
  cutoffWindow: number;
  selectedEntity: string | null;
  onSelectEntity: (name: string) => void;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const [showPredicted, setShowPredicted] = useState(true);

  const width = 640;
  const height = 470;
  const byName = new Map(nodes.map((n) => [n.name, n]));
  const observedSet = new Set(observedEdges.map((e) => `${e.source}->${e.target}`));

  const predicted = predictedEdges
    .filter((e) => e.probability > 0.15)
    .filter((e) => !observedSet.has(`${e.source}->${e.target}`))
    .slice(0, 10);

  const nodeRole = (n: GraphNode) => n.role;

  return (
    <div>
      <div className="chart-legend" style={{ paddingBottom: 6 }}>
        <span className="lg-item">
          <span className="swatch" style={{ background: "var(--ink-3)", width: 14, height: 3 }} />
          observed communication
        </span>
        <span className="lg-item dashed" style={{ color: "var(--task-4)" }}>
          <span className="swatch" style={{ borderColor: "var(--task-4)" }} />
          predicted (marginal, not confirmed)
        </span>
        <button
          className="btn ghost small"
          style={{ marginLeft: "auto" }}
          onClick={() => setShowPredicted((v) => !v)}
          aria-pressed={showPredicted}
        >
          {showPredicted ? "Hide predicted" : "Show predicted"}
        </button>
      </div>
      <div className="chart-frame">
        <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", display: "block" }} role="img"
          aria-label="observed communication graph with predicted candidate edges">
          <defs>
            <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="rgba(255,255,255,0.14)" />
              <stop offset="100%" stopColor="rgba(255,255,255,0)" />
            </radialGradient>
          </defs>

          {/* observed edges */}
          {observedEdges.map((e, i) => {
            const a = byName.get(e.source);
            const b = byName.get(e.target);
            if (!a || !b) return null;
            const dim =
              selectedEntity != null &&
              e.source !== selectedEntity &&
              e.target !== selectedEntity;
            const recency =
              (e.last_window - (cutoffWindow - 20)) / 20; // 0..1 across the clip
            return (
              <line
                key={`o-${i}`}
                className="g-edge"
                style={{ animationDelay: `${Math.min(i * 22, 420)}ms` }}
                x1={(a.x / 100) * width}
                y1={(a.y / 100) * height}
                x2={(b.x / 100) * width}
                y2={(b.y / 100) * height}
                stroke="var(--ink-3)"
                strokeWidth={1 + Math.min(recency, 1) * 1.2}
                opacity={dim ? 0.12 : 0.22 + Math.min(recency, 1) * 0.4}
              />
            );
          })}

          {/* predicted candidate edges — dashed, distinct legend */}
          {showPredicted &&
            predicted.map((e, i) => {
              const a = byName.get(e.source);
              const b = byName.get(e.target);
              if (!a || !b) return null;
              return (
                <line
                  key={`p-${i}`}
                  className="g-edge"
                  style={{ animationDelay: `${280 + i * 45}ms` }}
                  x1={(a.x / 100) * width}
                  y1={(a.y / 100) * height}
                  x2={(b.x / 100) * width}
                  y2={(b.y / 100) * height}
                  stroke="var(--task-4)"
                  strokeWidth={1.3}
                  strokeDasharray="4 5"
                  opacity={0.28 + e.probability * 0.55}
                />
              );
            })}

          {/* nodes */}
          {nodes.map((n, i) => {
            const cx = (n.x / 100) * width;
            const cy = (n.y / 100) * height;
            const active =
              selectedEntity === n.name || hover === n.name;
            const color = ROLE_COLORS[nodeRole(n)] ?? "#8b95a5";
            return (
              <g
                key={n.slot}
                className="g-node"
                style={{ animationDelay: `${Math.min(i * 34, 500)}ms`, cursor: "pointer" }}
                transform={`translate(${cx},${cy})`}
                onMouseEnter={() => setHover(n.name)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelectEntity(n.name)}
              >
                {active && <circle r={26} fill="url(#nodeGlow)" />}
                <circle
                  r={active ? 9.5 : 7.5}
                  fill={color}
                  fillOpacity={active ? 1 : 0.82}
                  stroke="var(--chart)"
                  strokeWidth={2}
                />
                {(active || nodes.length <= 16) && (
                  <text
                    y={-14}
                    textAnchor="middle"
                    fontSize={10}
                    fill={active ? "var(--ink)" : "var(--ink-2)"}
                    fontFamily="var(--mono)"
                  >
                    {n.name.split(".")[0]}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {hover && (
        <div className="muted" style={{ padding: "8px 4px 0" }}>
          {hover} · {byName.get(hover)?.role}
        </div>
      )}
    </div>
  );
}
