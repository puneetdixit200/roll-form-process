import { useEffect, useMemo, useState } from "react";
import { createVisualTarget, generateVisualFlower, getVisualDatasetStatus } from "./api";
import { exampleProfile, ProfileSketcher } from "./ProfileSketcher";
import type { VisualCandidate, VisualProfile, VisualRun } from "./types";

export default function VisualFlowerWorkspace() {
  const [profile, setProfile] = useState<VisualProfile>(exampleProfile());
  const [run, setRun] = useState<VisualRun | null>(null);
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [passIndex, setPassIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [stationMode, setStationMode] = useState("EXACT");
  const [stationCount, setStationCount] = useState(16);
  const [candidateLimit, setCandidateLimit] = useState(3);
  const [message, setMessage] = useState("");
  const [dataset, setDataset] = useState<{ available: boolean; flower_count: number; pass_count: number; warning?: string } | null>(null);
  const candidate: VisualCandidate | undefined = run?.candidates[candidateIndex];
  const currentPass = candidate?.passes[passIndex];

  useEffect(() => { getVisualDatasetStatus().then(setDataset).catch(() => setDataset({ available: false, flower_count: 0, pass_count: 0, warning: "Backend unavailable" })); }, []);
  useEffect(() => {
    if (!playing || !candidate || candidate.passes.length < 2) return;
    const timer = window.setInterval(() => setPassIndex((value) => (value + 1) % candidate.passes.length), 900);
    return () => window.clearInterval(timer);
  }, [candidate, playing]);

  const validation = useMemo(() => {
    const duplicate = profile.vertices.some((point, index) => index > 0 && point.x === profile.vertices[index - 1].x && point.y === profile.vertices[index - 1].y);
    return { valid: profile.vertices.length >= 2 && profile.segments.length >= 1 && !duplicate, duplicate };
  }, [profile]);

  async function generate() {
    try {
      setMessage("Canonicalizing and matching historical passes...");
      const target = await createVisualTarget(profile);
      const next = await generateVisualFlower(target.target_id, { station_mode: stationMode, exact_station_count: stationCount, candidate_limit: candidateLimit, allow_mirror_matching: true });
      setRun(next); setCandidateIndex(0); setPassIndex(0); setMessage("Candidate sequences ready for engineer review.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Generation failed"); }
  }

  function downloadJson(name: string, value: unknown) {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
    link.download = name; link.click(); URL.revokeObjectURL(link.href);
  }
  function saveTarget() { downloadJson(`${profile.profile_id}.json`, profile); }
  function exportCandidate() { if (candidate) downloadJson(`${candidate.candidate_id}.json`, { schema_version: 1, export_type: "VISUAL_FLOWER_CANDIDATE", candidate, source_cad_included: false }); }
  function loadTarget(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return;
    if (!file.name.toLowerCase().endsWith(".json")) { setMessage("CAD upload must first be converted through the existing offline extraction workflow; load its canonical JSON profile here."); return; }
    file.text().then((text) => { try { setProfile(JSON.parse(text) as VisualProfile); setMessage("Target loaded. Backend validation will run on generation."); } catch { setMessage("Target JSON could not be read."); } });
  }
  function passPoints(points: number[][]) { return points.map((point) => point.join(",")).join(" "); }

  return <section className="visual-workspace">
    <h2>Visual Flower Generator</h2>
    <p className="notice"><strong>Visual prototype only.</strong> Similarity and confidence refer to geometry appearance, not manufacturing feasibility.</p>
    <div className="visual-layout">
      <div><h3>Target Profile</h3><ProfileSketcher profile={profile} onChange={setProfile} />
        <div className="visual-controls"><button onClick={saveTarget}>Save target JSON</button><label>Load target profile <input type="file" accept="application/json,.dxf,.dwg" onChange={loadTarget} /></label><label>Station mode <select value={stationMode} onChange={(event) => setStationMode(event.target.value)}><option value="EXACT">Exact</option><option value="AUTOMATIC">Automatic</option><option value="RANGE">Range</option></select></label><label>Exact station count <input type="number" min={8} max={28} value={stationCount} onChange={(event) => setStationCount(Number(event.target.value))} /></label><label>Candidates <input type="number" min={1} max={3} value={candidateLimit} onChange={(event) => setCandidateLimit(Number(event.target.value))} /></label><button disabled={!validation.valid} onClick={generate}>Generate Flower Sequence</button></div>
        <p>{validation.valid ? "Profile valid for visual generation." : "Profile needs at least two connected, non-duplicate points."}</p><p>{dataset?.available ? `Historical evidence: ${dataset.flower_count} flowers, ${dataset.pass_count} passes.` : dataset?.warning ?? "Historical dataset status unknown."}</p>
      </div>
      <div><h3>Candidate Sequence</h3>{run?.candidates.length ? <>
        <div className="candidate-tabs">{run.candidates.map((item, index) => <button key={item.candidate_id} className={candidateIndex === index ? "active" : ""} onClick={() => { setCandidateIndex(index); setPassIndex(0); }}>{item.candidate_style} · {item.station_count} stations · {item.visual_confidence.score.toFixed(1)}</button>)}</div>
        {candidate && <><div className="metrics"><Metric label="Visual confidence" value={`${candidate.visual_confidence.score.toFixed(1)} / 100`} /><Metric label="Band" value={candidate.visual_confidence.band} /><Metric label="Current pass" value={`${passIndex + 1} / ${candidate.station_count}`} /><Metric label="Smoothness" value={`${candidate.visual_confidence.progression_smoothness.toFixed(1)}`} /></div>
          <div className="visual-controls"><button onClick={() => setPlaying((value) => !value)}>{playing ? "Pause" : "Play"}</button><button onClick={() => setPassIndex((value) => Math.max(0, value - 1))}>Previous</button><button onClick={() => setPassIndex((value) => Math.min(candidate.passes.length - 1, value + 1))}>Next</button><button onClick={exportCandidate}>Download candidate JSON</button></div>
          <svg role="img" aria-label="Generated pass viewer" viewBox="-2 -2 4 4" style={{ width: "100%", minHeight: 300, border: "1px solid #b7c0ca" }}>{candidate.passes.map((item, index) => <polyline key={item.pass_id} points={passPoints(item.profile.points)} fill="none" stroke={index === passIndex ? "#c46b00" : "#8aa5b9"} strokeWidth={index === passIndex ? ".025" : ".008"} opacity={index === passIndex ? 1 : .2} />)}</svg>
          <input aria-label="Station slider" type="range" min={0} max={candidate.passes.length - 1} value={passIndex} onChange={(event) => setPassIndex(Number(event.target.value))} /><p>Pass {currentPass?.order}: {currentPass?.visual_confidence.band}. Best historical match: {currentPass?.historical_match.best_match?.source_flower_id ?? "none"} / {currentPass?.historical_match.best_match?.source_pass_id ?? "none"}</p><p>Visual similarity: {currentPass?.historical_match.best_match ? `${(currentPass.historical_match.best_match.overall_score * 100).toFixed(1)}%` : "not supported"}. Evidence coverage: {currentPass?.historical_match.best_match ? `${(currentPass.historical_match.best_match.evidence_coverage * 100).toFixed(0)}%` : "0%"}.</p>
        </>}</> : <p>Load the synthetic example, validate it, then generate a sequence.</p>}<p>{message}</p></div>
    </div>
  </section>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div className="metric"><small>{label}</small><strong>{value}</strong></div>; }
