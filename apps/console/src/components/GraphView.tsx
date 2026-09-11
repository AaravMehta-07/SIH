import { useId, useMemo, useState } from "react";
import { Database, Maximize, Minus, Monitor, Plus, Server, Shield, Network, X } from "lucide-react";
import type { CandidateEdge, GraphNode, ObservedEdge } from "../types";

export function GraphView({ nodes, observedEdges, predictedEdges, cutoffWindow, selectedEntity, onSelectEntity }: {
  nodes: GraphNode[]; observedEdges: ObservedEdge[]; predictedEdges: CandidateEdge[];
  cutoffWindow: number; selectedEntity: string | null; onSelectEntity: (name: string) => void;
}) {
  const id = useId().replace(/:/g, "");
  const [zoom, setZoom] = useState(1);
  const [showPredicted, setShowPredicted] = useState(true);
  const [neighborsOnly, setNeighborsOnly] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [edge, setEdge] = useState<ObservedEdge | CandidateEdge | null>(null);
  const [localSelection, setLocalSelection] = useState<string | null>(null);
  const selection = selectedEntity ?? localSelection;
  const focus = hover ?? selection;
  const width = 720;
  const columns = nodes.length > 24 ? 6 : 3;
  const rows = Math.ceil(nodes.length / columns);
  const height = Math.max(460, rows * 92 + 90);
  const positions = useMemo(() => {
    // Layout is presentation only; model values and topology are unchanged.
    const sorted = [...nodes].sort((a, b) => a.role.localeCompare(b.role) || a.name.localeCompare(b.name));
    return new Map(sorted.map((n, i) => [n.name, {
      ...n, x: 120 + (i % columns) * (480 / (columns - 1)), y: 70 + Math.floor(i / columns) * 92,
    }]));
  }, [nodes, columns]);
  const connected = new Set([focus]);
  for (const e of observedEdges) {
    if (e.source === focus) connected.add(e.target);
    if (e.target === focus) connected.add(e.source);
  }
  const predicted = predictedEdges.slice(0, 12);
  const nodeIcon = (role: string) => role.includes("database") ? Database : role.includes("workstation") ? Monitor : role.includes("security") ? Shield : Server;
  const select = (name: string) => { setLocalSelection(name); setEdge(null); onSelectEntity(name); };
  const connection = (e: ObservedEdge | CandidateEdge, predicted: boolean, i: number) => {
    const a = positions.get(e.source), b = positions.get(e.target);
    if (!a || !b) return null;
    const related = !focus || e.source === focus || e.target === focus;
    if (neighborsOnly && !related) return null;
    const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
    const sx = a.x + dx / length * 28, sy = a.y + dy / length * 28;
    const tx = b.x - dx / length * 32, ty = b.y - dy / length * 32;
    const bend = predicted ? 36 : 15;
    const d = `M${sx},${sy} Q${(sx + tx) / 2 - dy / length * bend},${(sy + ty) / 2 + dx / length * bend} ${tx},${ty}`;
    const description = predicted ? `Predicted communication: ${e.source} to ${e.target}, ${((e as CandidateEdge).probability * 100).toFixed(1)}% marginal probability, not confirmed` : `Observed communication: ${e.source} to ${e.target}, windows ${(e as ObservedEdge).first_window} to ${(e as ObservedEdge).last_window}`;
    return <g key={`${predicted}-${i}`} className={`network-edge ${related ? "related" : "dimmed"}`}>
      <path d={d} fill="none" className={predicted ? "predicted-line" : "observed-line"} markerEnd={`url(#${id}-${predicted ? "pred" : "obs"})`} />
      <path d={d} fill="none" stroke="transparent" strokeWidth={12} role="button" tabIndex={0} aria-label={description}
        onClick={() => setEdge(e)} onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setEdge(e); } }}><title>{description}</title></path>
    </g>;
  };
  return <div className="network-tool">
    <div className="network-toolbar">
      <span className="network-caption"><Network size={15} /> Topology <span> / {cutoffWindow}</span></span>
      <div className="network-controls">
        <button title="Zoom out" aria-label="Zoom out" disabled={zoom <= 0.7} onClick={() => setZoom(v => Math.max(0.7, v - 0.15))}><Minus size={15} /></button>
        <button title="Fit network" aria-label="Fit network" onClick={() => setZoom(1)}><Maximize size={15} /></button>
        <button title="Zoom in" aria-label="Zoom in" disabled={zoom >= 1.6} onClick={() => setZoom(v => Math.min(1.6, v + 0.15))}><Plus size={15} /></button>
      </div>
    </div>
    <div className="network-viewport">
      <svg viewBox={`0 0 ${width} ${height}`} aria-label="Directed observed and predicted network" className="network-canvas">
        <defs>
          <pattern id={`${id}-grid`} width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="var(--network-grid)" strokeWidth="0.5" /></pattern>
          <marker id={`${id}-obs`} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7" fill="var(--network-edge)" /></marker>
          <marker id={`${id}-pred`} markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7" fill="var(--network-predicted)" /></marker>
        </defs>
        <rect width={width} height={height} fill={`url(#${id}-grid)`} />
        <g style={{ transform: `translate(${width / 2}px, ${height / 2}px) scale(${zoom}) translate(${-width / 2}px, ${-height / 2}px)`, transition: "transform 240ms var(--ease-out)" }}>
          {observedEdges.map((e, i) => connection(e, false, i))}
          {showPredicted && predicted.map((e, i) => connection(e, true, i))}
          {[...positions.values()].map((n) => {
            const active = selection === n.name, highlighted = hover === n.name;
            const Icon = nodeIcon(n.role);
            const dimmed = neighborsOnly && focus && !connected.has(n.name);
            return <g key={n.name} transform={`translate(${n.x},${n.y})`} className={`network-node ${active ? "selected" : ""} ${highlighted ? "hovered" : ""} ${dimmed ? "dimmed" : ""}`}
              role="button" tabIndex={0} aria-label={`${n.name}, ${n.role}`} aria-pressed={active}
              onClick={() => select(n.name)} onMouseEnter={() => setHover(n.name)} onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(n.name)} onBlur={() => setHover(null)}
              onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(n.name); } }}>
              <title>{n.name} / {n.role}</title>
              <circle className="node-selection-ring" r="29" />
              <rect className="node-face" x="-22" y="-22" width="44" height="44" rx="7" />
              <Icon x={-10} y={-10} width={20} height={20} className="node-icon" aria-hidden="true" />
              {(nodes.length <= 24 || active || highlighted) && <text y="43" textAnchor="middle" className="node-label">{n.name.split(".")[0].slice(0, 22)}</text>}
            </g>;
          })}
        </g>
      </svg>
    </div>
    <div className="network-legend chart-legend">
      <span className="lg-item"><i className="edge-sample" />Observed · directed</span>
      <label><input type="checkbox" checked={showPredicted} onChange={e => setShowPredicted(e.target.checked)} /><i className="edge-sample predicted" />Predicted · marginal</label>
      <label><input type="checkbox" checked={neighborsOnly} onChange={e => setNeighborsOnly(e.target.checked)} />Focus connections</label>
    </div>
    <div className="network-inspector" aria-live="polite">
      {edge ? <><div><strong>{edge.source} → {edge.target}</strong><span>{"probability" in edge ? `Predicted communication · ${(edge.probability * 100).toFixed(1)}% marginal probability · not confirmed traffic` : `Observed communication · windows ${edge.first_window}–${edge.last_window}`}</span></div><button aria-label="Close connection details" title="Close connection details" onClick={() => setEdge(null)}><X size={15} /></button></> : <div><strong>{focus ?? "Network scope"}</strong><span>{focus ? positions.get(focus)?.role : `${nodes.length} entities · ${observedEdges.length} observed directed pairs`}</span></div>}
    </div>
  </div>;
}
