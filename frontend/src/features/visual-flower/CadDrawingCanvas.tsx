import { useEffect, useMemo, useRef, useState } from "react";
import type { CadDrawingPreview, CadPreviewPrimitive } from "./types";

type Candidate = { profile_id: string; source_handles?: string[] };
type Point = [number, number];

function arcPath(item: CadPreviewPrimitive, flip: (point: Point) => string) {
  if (item.type !== "ARC" || !item.center || item.radius === undefined || !item.start || !item.end) return null;
  const start = item.start as Point; const end = item.end as Point; const center = item.center as Point;
  const a0 = Math.atan2(start[1] - center[1], start[0] - center[0]);
  const a1 = Math.atan2(end[1] - center[1], end[0] - center[0]);
  const delta = item.clockwise ? (a0 - a1) % (2 * Math.PI) : (a1 - a0) % (2 * Math.PI);
  return `M ${flip(start)} A ${item.radius} ${item.radius} 0 ${delta > Math.PI ? 1 : 0} ${item.clockwise ? 0 : 1} ${flip(end)}`;
}

function primitivePath(item: CadPreviewPrimitive, flip: (point: Point) => string) {
  if (item.type === "ARC") return arcPath(item, flip);
  if (item.type === "LINE" && item.start && item.end) return `M ${flip(item.start as Point)} L ${flip(item.end as Point)}`;
  if (item.type === "POLYLINE" && item.points?.length) return item.points.map((point, index) => `${index ? "L" : "M"} ${flip(point as Point)}`).join(" ") + (item.closed ? " Z" : "");
  if (item.type === "CIRCLE" && item.center && item.radius !== undefined) {
    const [x, y] = item.center; const r = item.radius;
    return `M ${x - r} ${-y} A ${r} ${r} 0 1 0 ${x + r} ${-y} A ${r} ${r} 0 1 0 ${x - r} ${-y}`;
  }
  return null;
}

function boundsFor(items: CadPreviewPrimitive[]) {
  const points = items.flatMap((item) => {
    if (item.points) return item.points as Point[];
    return item.start && item.end ? [item.start as Point, item.end as Point] : [];
  });
  if (!points.length) return null;
  const xs = points.map((point) => point[0]); const ys = points.map((point) => point[1]);
  return { min_x: Math.min(...xs), min_y: Math.min(...ys), max_x: Math.max(...xs), max_y: Math.max(...ys) };
}

export function CadDrawingCanvas({ preview, candidates, selectedId, onSelect }: { preview: CadDrawingPreview; candidates: Candidate[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const [zoom, setZoom] = useState(1); const [pan, setPan] = useState<Point>([0, 0]);
  const [focusBounds, setFocusBounds] = useState(preview.bounds);
  const [layers, setLayers] = useState<Record<string, boolean>>({}); const [hoveredId, setHoveredId] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number; pan: Point } | null>(null);
  useEffect(() => { setLayers(Object.fromEntries(preview.layers.map((layer) => [layer.name, layer.visible_by_default]))); setZoom(1); setPan([0, 0]); setFocusBounds(preview.bounds); setHoveredId(null); }, [preview.import_id, preview.layers, preview.bounds]);
  const b = focusBounds; const margin = Math.max(b.width, b.height, 1) * 0.06;
  const viewBox = `${b.min_x - margin + pan[0]} ${-(b.max_y + margin) + pan[1]} ${(b.width + margin * 2) / zoom} ${(b.height + margin * 2) / zoom}`;
  const selectedHandles = useMemo(() => new Set(candidates.find((item) => item.profile_id === selectedId)?.source_handles ?? []), [candidates, selectedId]);
  const hoveredHandles = useMemo(() => new Set(candidates.find((item) => item.profile_id === hoveredId)?.source_handles ?? []), [candidates, hoveredId]);
  const flip = (point: Point) => `${point[0]} ${-point[1]}`;
  const fit = (items: CadPreviewPrimitive[] = preview.primitives) => { const next = boundsFor(items); if (!next) return; setFocusBounds({ ...next, width: Math.max(next.max_x - next.min_x, 1e-9), height: Math.max(next.max_y - next.min_y, 1e-9) }); setPan([0, 0]); setZoom(1); };
  function beginPan(event: React.PointerEvent<SVGSVGElement>) { if (event.button !== 0) return; event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.clientX, y: event.clientY, pan }; }
  function movePan(event: React.PointerEvent<SVGSVGElement>) { if (!drag.current) return; const scale = Math.max(b.width, b.height, 1) / Math.max(event.currentTarget.clientWidth, 1); setPan([drag.current.pan[0] - (event.clientX - drag.current.x) * scale, drag.current.pan[1] + (event.clientY - drag.current.y) * scale]); }
  function endPan(event: React.PointerEvent<SVGSVGElement>) { if (drag.current) event.currentTarget.releasePointerCapture(event.pointerId); drag.current = null; }
  return <div className="cad-drawing-preview">
    <div className="visual-controls"><button type="button" onClick={() => setZoom((value) => Math.min(8, value * 1.25))}>Zoom +</button><button type="button" onClick={() => setZoom((value) => Math.max(.25, value / 1.25))}>Zoom −</button><button type="button" onClick={() => fit()}>Fit drawing</button><button type="button" disabled={!selectedId} onClick={() => fit(preview.primitives.filter((item) => selectedHandles.has(item.source_handle)))}>Fit selected</button><span>Pan: drag canvas</span></div>
    <svg data-testid="cad-drawing-canvas" role="img" aria-label="Imported CAD drawing" viewBox={viewBox} onWheel={(event) => { event.preventDefault(); setZoom((value) => Math.max(.25, Math.min(8, value * (event.deltaY < 0 ? 1.1 : .9)))); }} onPointerDown={beginPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={endPan}>
      {preview.primitives.filter((item) => layers[item.layer] !== false).map((item) => { const d = primitivePath(item, flip); if (!d) return null; const owner = candidates.find((candidate) => candidate.source_handles?.includes(item.source_handle)); const active = selectedHandles.has(item.source_handle); const hover = hoveredHandles.has(item.source_handle); return <path key={item.primitive_id} d={d} fill="none" stroke={active ? "#d66f00" : hover ? "#155783" : owner ? "#4d78a8" : "#aab6c1"} strokeWidth={active ? 1.8 : hover ? 1.3 : .7} opacity={active || hover || !owner ? 1 : .65} onPointerEnter={() => owner && setHoveredId(owner.profile_id)} onPointerLeave={() => setHoveredId(null)} onClick={(event) => { event.stopPropagation(); if (owner) onSelect(owner.profile_id); }} />; })}
    </svg>
    <div className="cad-preview-meta"><span>Units: {preview.units ?? "unknown"}</span><span>Entities: {preview.modelspace_entity_count}</span><span>Supported: {preview.supported_primitive_count}</span><span>Candidates: {candidates.length}</span></div>
    {Object.keys(preview.unsupported_entity_counts).length > 0 && <p className="notice">Unsupported preview entities: {Object.entries(preview.unsupported_entity_counts).map(([kind, count]) => `${kind} × ${count}`).join(", ")}. These entities are present in the source drawing but are not part of the visual forming-profile preview.</p>}
    <div className="cad-layers">{preview.layers.map((layer) => <label key={layer.name}><input type="checkbox" checked={layers[layer.name] ?? layer.visible_by_default} onChange={(event) => setLayers((value) => ({ ...value, [layer.name]: event.target.checked }))} />{layer.name} ({layer.entity_count})</label>)}</div>
  </div>;
}
