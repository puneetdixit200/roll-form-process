import { useEffect, useMemo, useState } from "react";
import { getHistoricalFlower, getHistoricalPass } from "./api";
import type { HistoricalFlowerDetail, HistoricalPassDetail } from "./types";

type SourcePass = HistoricalPassDetail;
type SourceFlower = HistoricalFlowerDetail;

function pointsFor(pass: SourcePass): number[][] {
  if (pass.geometry?.points?.length) return pass.geometry.points;
  if (pass.points?.length) return pass.points;
  const vector = pass.shape_vector ?? [];
  return Array.from({ length: Math.floor(vector.length / 2) }, (_, index) => [vector[index * 2], vector[index * 2 + 1]]);
}

export function HistoricalSourceFlowerExplorer({ flowerId, passId, generatedStation, onBack }: { flowerId: string; passId: string; generatedStation: number; onBack: () => void }) {
  const [flower, setFlower] = useState<SourceFlower | null>(null);
  const [passDetail, setPassDetail] = useState<SourcePass | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { let active = true; setSourceError(null); setPassDetail(null); getHistoricalFlower(flowerId).then((result) => { if (!active) return; const requestedIndex = (result.passes ?? []).findIndex((item) => item.pass_id === passId); if (requestedIndex < 0) { setFlower(result); setSourceError("Historical source pass is unavailable in the active dataset."); return; } setFlower(result); setIndex(requestedIndex); }).catch(() => { if (active) setFlower(null); }); return () => { active = false; }; }, [flowerId, passId]);
  useEffect(() => { const selected = flower?.passes[index]; if (!selected) return; let active = true; setPassDetail(null); getHistoricalPass(flowerId, selected.pass_id).then((result) => { if (active) setPassDetail(result); }).catch(() => { if (active) setPassDetail(null); }); return () => { active = false; }; }, [flowerId, flower, index]);
  useEffect(() => { if (!playing || !flower?.passes.length) return; const timer = window.setInterval(() => setIndex((value) => (value + 1) % flower.passes.length), 800); return () => window.clearInterval(timer); }, [playing, flower]);
  const selectedPass = flower?.passes[index];
  const current = passDetail?.pass_id === selectedPass?.pass_id ? passDetail : selectedPass;
  const points = useMemo(() => pointsFor(current ?? { pass_id: "" }), [current]);
  const bounds = useMemo(() => { const xs = points.map((p) => p[0]); const ys = points.map((p) => p[1]); return xs.length ? { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) } : { minX: -1, maxX: 1, minY: -1, maxY: 1 }; }, [points]);
  const width = Math.max(bounds.maxX - bounds.minX, 1); const height = Math.max(bounds.maxY - bounds.minY, 1); const path = points.map((point, i) => `${i ? "L" : "M"} ${point[0]} ${-point[1]}`).join(" ");
  return <section className="historical-source-explorer" aria-label="Historical source flower explorer">
    <header><h3>Historical Source Flower · {flowerId}</h3><p>Generated station {generatedStation} · source pass {current?.display_order ?? index + 1} / {flower?.station_count ?? "…"}</p><button type="button" onClick={onBack}>Back to generated station</button></header>
    {!flower ? <p>Historical source could not be loaded.</p> : sourceError ? <p role="alert">{sourceError}</p> : <>
      <div className="visual-controls"><button type="button" disabled={index <= 0} onClick={() => setIndex((value) => value - 1)}>Previous</button><button type="button" onClick={() => setPlaying((value) => !value)}>{playing ? "Pause" : "Play"}</button><button type="button" disabled={index >= flower.passes.length - 1} onClick={() => setIndex((value) => value + 1)}>Next</button></div>
      <div className="historical-source-passes">{flower.passes.map((item, itemIndex) => <button className={itemIndex === index ? "selected" : ""} type="button" key={item.pass_id} onClick={() => setIndex(itemIndex)}>P{item.display_order ?? itemIndex + 1}</button>)}</div>
      <svg role="img" aria-label={`Historical pass ${current?.pass_id ?? ""}`} viewBox={`${bounds.minX - width * .1} ${-bounds.maxY - height * .1} ${width * 1.2} ${height * 1.2}`}><path d={path} fill="none" stroke="#155783" strokeWidth={Math.max(width, height) * .012} /></svg>
      <p>Topology: {flower.topology ?? "unknown"} · Dimensions: {current?.width ?? "n/a"} × {current?.height ?? "n/a"}</p>
      <h4>Historical roller design evidence</h4>{passDetail?.roller_roles?.length ? passDetail.roller_roles.map((role) => <div key={role.role}><strong>{role.role}</strong>{role.designs.map((design) => <span key={`${design.design_id}-${design.geometry_revision_id}`} className="evidence-chip">{design.design_id}{design.geometry_revision_id ? ` / ${design.geometry_revision_id}` : ""} · {design.confirmation_status ?? "UNCONFIRMED"}</span>)}</div>) : <p>No reviewed roller design evidence is recorded for this source pass.</p>}
    </>}
  </section>;
}
