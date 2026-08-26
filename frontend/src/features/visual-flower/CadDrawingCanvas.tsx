import { useMemo, useState } from "react";
import type { CadDrawingPreview, CadPreviewPrimitive } from "./types";

type Candidate = { profile_id: string; source_handles?: string[] };

function arcPath(item: CadPreviewPrimitive, flip: (point: [number, number]) => string) {
  if (item.type !== "ARC" || !item.center || item.radius === undefined) return null;
  const start = item.start as [number, number]; const end = item.end as [number, number];
  const a0 = Math.atan2(start[1] - item.center[1], start[0] - item.center[0]);
  const a1 = Math.atan2(end[1] - item.center[1], end[0] - item.center[0]);
  let delta = a1 - a0; if (item.clockwise && delta > 0) delta -= 2 * Math.PI; if (!item.clockwise && delta < 0) delta += 2 * Math.PI;
  return `M ${flip(start)} A ${item.radius} ${item.radius} 0 ${Math.abs(delta) > Math.PI ? 1 : 0} ${item.clockwise ? 0 : 1} ${flip(end)}`;
}

export function CadDrawingCanvas({ preview, candidates, selectedId, onSelect }: { preview: CadDrawingPreview; candidates: Candidate[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const [zoom, setZoom] = useState(1); const [pan, setPan] = useState<[number, number]>([0, 0]); const [layers, setLayers] = useState<Record<string, boolean>>(() => Object.fromEntries(preview.layers.map((layer) => [layer.name, true])));
  const b = preview.bounds; const margin = Math.max(b.width, b.height, 1) * 0.06; const viewBox = `${b.min_x - margin + pan[0]} ${-(b.max_y + margin) + pan[1]} ${(b.width + margin * 2) / zoom} ${(b.height + margin * 2) / zoom}`;
  const selectedHandles = useMemo(() => new Set(candidates.find((item) => item.profile_id === selectedId)?.source_handles ?? []), [candidates, selectedId]);
  const flip = (point: [number, number]) => `${point[0]} ${-point[1]}`;
  function path(item: CadPreviewPrimitive) {
    if (item.type === "ARC") return arcPath(item, flip);
    if (item.type === "LINE") return `M ${flip(item.start as [number, number])} L ${flip(item.end as [number, number])}`;
    if (item.type === "POLYLINE" && item.points) return item.points.map((point, i) => `${i ? "L" : "M"} ${flip(point as [number, number])}`).join(" ") + (item.closed ? " Z" : "");
    if (item.type === "CIRCLE") return `M ${item.center![0] - item.radius!} ${-item.center![1]} A ${item.radius} ${item.radius} 0 1 0 ${item.center![0] + item.radius!} ${-item.center![1]} A ${item.radius} ${item.radius} 0 1 0 ${item.center![0] - item.radius!} ${-item.center![1]}`;
    return null;
  }
  return <div className="cad-drawing-preview"><div className="visual-controls"><button onClick={() => setZoom((value) => value * 1.25)}>Zoom +</button><button onClick={() => setZoom((value) => Math.max(.25, value / 1.25))}>Zoom −</button><button onClick={() => { setZoom(1); setPan([0, 0]); }}>Fit drawing</button></div><svg data-testid="cad-drawing-canvas" role="img" aria-label="Imported CAD drawing" viewBox={viewBox} onWheel={(event) => { event.preventDefault(); setZoom((value) => Math.max(.25, Math.min(8, value * (event.deltaY < 0 ? 1.1 : .9)))); }}><g>{preview.primitives.filter((item) => layers[item.layer]).map((item) => { const d = path(item); if (!d) return null; const active = selectedHandles.has(item.source_handle); const owner = candidates.find((candidate) => candidate.source_handles?.includes(item.source_handle)); return <path key={item.primitive_id} d={d} fill="none" stroke={active ? "#c46b00" : owner ? "#4d78a8" : "#9aa8b5"} strokeWidth={active ? 1.5 : .7} opacity={active || !owner ? 1 : .65} onClick={() => owner && onSelect(owner.profile_id)} />; })}</g></svg><div className="cad-preview-meta"><span>Units: {preview.units ?? "unknown"}</span><span>Entities: {preview.modelspace_entity_count}</span><span>Supported: {preview.supported_primitive_count}</span><span>Candidates: {candidates.length}</span></div><div className="cad-layers">{preview.layers.map((layer) => <label key={layer.name}><input type="checkbox" checked={layers[layer.name] ?? true} onChange={(event) => setLayers((value) => ({ ...value, [layer.name]: event.target.checked }))} />{layer.name} ({layer.entity_count})</label>)}</div></div>;
}
