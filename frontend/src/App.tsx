import { useEffect, useMemo, useState } from "react";
import { applyReview, artifactUrl, getArtifacts, getJob, getProject, getReportData, uploadDrawing } from "./api/client";
import type { CompositeFlower, FlowerPass, JobRecord, ProjectRecord, ReportData, StepChange } from "./types/report";
import "./styles.css";

const STAGES = ["UPLOADED", "CONVERTING", "PARSING", "DETECTING_FLOWERS", "EXTRACTING_PASSES", "ANALYSING_GEOMETRY", "GENERATING_REPORT", "CANDIDATE_READY"];

export default function App() {
  const [projectId, setProjectId] = useState("");
  const [jobId, setJobId] = useState("");
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [report, setReport] = useState<ReportData | null>(null);
  const [artifacts, setArtifacts] = useState<Record<string, { sha256: string }>>({});
  const [selectedFlower, setSelectedFlower] = useState(0);
  const [selectedPass, setSelectedPass] = useState(0);
  const [mode, setMode] = useState("single");
  const flower = report?.composite_flowers[selectedFlower];
  const pass = flower?.passes[selectedPass];

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const projectParam = params.get("project_id");
    const jobParam = params.get("job_id");
    if (projectParam && jobParam && !projectId && !jobId) {
      setProjectId(projectParam);
      setJobId(jobParam);
    }
  }, [projectId, jobId]);

  useEffect(() => {
    if (!projectId || !jobId) return;
    const timer = setInterval(async () => {
      const nextJob = await getJob(jobId);
      setJob(nextJob);
      const nextProject = await getProject(projectId);
      setProject(nextProject);
      if (nextJob.status === "CANDIDATE_READY") {
        setReport(await getReportData(projectId));
        setArtifacts((await getArtifacts(projectId)).files);
        clearInterval(timer);
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [projectId, jobId]);

  async function onUpload(file: File) {
    const upload = await uploadDrawing(file);
    setProjectId(upload.project_id);
    setJobId(upload.job_id);
    setProject(await getProject(upload.project_id));
    setJob(await getJob(upload.job_id));
  }

  async function exportReview() {
    if (!projectId || !flower) return;
    const decisions = {
      schema_version: 1,
      drawing_units: { detected_unit: report?.project.units.detected ?? "Unitless", engineer_confirmed_unit: null, conversion_factor_to_mm: null, confirmed_by: "", notes: "" },
      composite_passes: flower.passes.map((p) => ({ pass_id: p.pass_id, confirmed: false, confirmed_order: p.engineer_confirmed_order, bend_zones_confirmed: false, notes: "" })),
      transition_reviews: flower.profile_step_changes.map((change) => ({ from_pass_id: change.from_pass_id, to_pass_id: change.to_pass_id, confirmed: false, selected_choice: null })),
    };
    const blob = new Blob([JSON.stringify(decisions, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "manual_review_decisions.json";
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function applyUnitReview() {
    if (!projectId) return;
    const updated = await applyReview(projectId, {
      schema_version: 1,
      drawing_units: { detected_unit: report?.project.units.detected ?? "Unitless", engineer_confirmed_unit: "mm", conversion_factor_to_mm: 1.0, confirmed_by: "engineer", notes: "" },
      composite_passes: [],
    });
    setProject(updated);
    setReport(await getReportData(projectId));
  }

  return (
    <main>
      <header className="top">
        <div>
          <h1>Rollform Extractor</h1>
          <p>Candidate extraction - not approved for production use</p>
        </div>
        <nav>{["Dashboard", "New Project / Upload", "Processing Progress", "Project Summary", "Flower Viewer", "Pass Detail", "What Changed", "Bend-Zone Progression", "Warnings", "Engineer Review", "Exports"].map((item) => <a href={`#${item.replaceAll(" ", "-")}`} key={item}>{item}</a>)}</nav>
      </header>
      <section id="Dashboard" className="panel"><Dashboard project={project} report={report} /></section>
      <section id="New-Project-/-Upload" className="panel"><Upload onUpload={onUpload} /></section>
      <section id="Processing-Progress" className="panel"><Progress job={job} /></section>
      <section id="Project-Summary" className="panel"><ProjectSummary project={project} report={report} /></section>
      <section id="Flower-Viewer" className="panel">
        <FlowerViewer projectId={projectId} report={report} flower={flower} pass={pass} selectedFlower={selectedFlower} selectedPass={selectedPass} mode={mode} onFlower={setSelectedFlower} onPass={setSelectedPass} onMode={setMode} />
      </section>
      <section id="Pass-Detail" className="panel"><PassDetail projectId={projectId} pass={pass} /></section>
      <section id="What-Changed" className="panel"><WhatChanged changes={flower?.profile_step_changes ?? []} /></section>
      <section id="Bend-Zone-Progression" className="panel"><BendProgression flower={flower} /></section>
      <section id="Warnings" className="panel"><Warnings report={report} /></section>
      <section id="Engineer-Review" className="panel"><EngineerReview onExport={exportReview} onApplyUnits={applyUnitReview} flower={flower} /></section>
      <section id="Exports" className="panel"><Exports projectId={projectId} artifacts={artifacts} /></section>
    </main>
  );
}

function Dashboard({ project, report }: { project: ProjectRecord | null; report: ReportData | null }) {
  const summary = project?.summary;
  return <><h2>Dashboard</h2><div className="metrics">
    <Metric label="Composite flowers" value={summary?.composite_flower_count ?? report?.composite_flowers.length ?? 0} />
    <Metric label="Candidate passes" value={summary?.candidate_pass_count ?? 0} />
    <Metric label="Bend zones" value={summary?.canonical_bend_zone_count ?? 0} />
    <Metric label="Confirmed transitions" value={summary?.confirmed_transition_count ?? 0} />
    <Metric label="Units" value={summary?.units_confirmed ? "Confirmed" : "Unconfirmed"} />
  </div></>;
}

function Upload({ onUpload }: { onUpload: (file: File) => void }) {
  return <><h2>New Project / Upload</h2><input aria-label="Upload DWG or DXF" type="file" accept=".dwg,.dxf" onChange={(event) => event.target.files?.[0] && onUpload(event.target.files[0])} /><p>Accepts one DWG or DXF. The original file is copied to immutable source storage before analysis.</p></>;
}

function Progress({ job }: { job: JobRecord | null }) {
  const stages = job?.stages ?? [];
  return <><h2>Processing Progress</h2><ol className="stage-list">{STAGES.map((stage) => <li key={stage}><strong>{stage}</strong><span>{stages.find((item) => item.stage === stage)?.status ?? "pending"}</span></li>)}</ol></>;
}

function ProjectSummary({ project, report }: { project: ProjectRecord | null; report: ReportData | null }) {
  return <><h2>Project Summary</h2><pre>{JSON.stringify({ status: project?.status, revision: project?.revision, source: project?.source, report: report?.project }, null, 2)}</pre></>;
}

function FlowerViewer(props: { projectId: string; report: ReportData | null; flower?: CompositeFlower; pass?: FlowerPass; selectedFlower: number; selectedPass: number; mode: string; onFlower: (i: number) => void; onPass: (i: number) => void; onMode: (m: string) => void }) {
  const { projectId, report, flower, pass } = props;
  const passes = flower?.passes ?? [];
  return <><h2>Flower Viewer</h2><div className="toolbar">
    {report?.composite_flowers.map((item, i) => <button className={i === props.selectedFlower ? "active" : ""} key={item.composite_flower_id} onClick={() => props.onFlower(i)}>{item.label}</button>)}
    <button onClick={() => props.onPass(Math.max(0, props.selectedPass - 1))}>Previous</button>
    <strong>{pass?.name ?? "No pass"} {passes.length ? `${props.selectedPass + 1} of ${passes.length}` : ""}</strong>
    <button onClick={() => props.onPass(Math.min(passes.length - 1, props.selectedPass + 1))}>Next</button>
    <input aria-label="Sequence slider" type="range" min="0" max={Math.max(0, passes.length - 1)} value={props.selectedPass} onChange={(e) => props.onPass(Number(e.target.value))} />
    <select aria-label="Direct pass selector" value={props.selectedPass} onChange={(e) => props.onPass(Number(e.target.value))}>{passes.map((item, i) => <option value={i} key={item.pass_id}>{item.name}</option>)}</select>
  </div><div className="toolbar">{["single", "previous-current", "overlay", "cumulative", "complete", "original-normalized", "strip-outline", "neutral-line", "outline-neutral", "bend-zones"].map((mode) => <button className={props.mode === mode ? "active" : ""} onClick={() => props.onMode(mode)} key={mode}>{mode}</button>)}</div>
  <Preview projectId={projectId} mode={props.mode} passes={passes} index={props.selectedPass} />
  <div className="cards">{passes.map((item, i) => <button className={`card ${i === props.selectedPass ? "active" : ""}`} onClick={() => props.onPass(i)} key={item.pass_id}><strong>{item.name}</strong><span>{item.profile_type}</span><span>Zones {item.physical_forming_bend_count}</span><span>Error {item.neutral_length_error_percent}</span></button>)}</div></>;
}

function Preview({ projectId, mode, passes, index }: { projectId: string; mode: string; passes: FlowerPass[]; index: number }) {
  const selected = passes[index];
  const imageFor = (p?: FlowerPass) => p ? artifactUrl(projectId, mode === "neutral-line" ? p.downloads.profile_neutral_line_png : mode === "strip-outline" ? p.downloads.profile_outline_png : p.downloads.profile_png) : "";
  const shown = mode === "complete" ? passes : mode === "cumulative" ? passes.slice(0, index + 1) : mode === "previous-current" ? [passes[index - 1], selected].filter(Boolean) as FlowerPass[] : [selected].filter(Boolean) as FlowerPass[];
  return <div className={`preview ${mode}`}>{shown.map((p) => <img key={p.pass_id} alt={p.name} src={imageFor(p)} />)}{mode === "bend-zones" && <BendTable pass={selected} />}</div>;
}

function PassDetail({ projectId, pass }: { projectId: string; pass?: FlowerPass }) {
  if (!pass) return <><h2>Pass Detail</h2><p>No pass selected.</p></>;
  const manufacturing = pass.features?.manufacturing?.values ?? {};
  const quality = pass.features?.quality;
  const metric = (name: string, fallback: unknown = null) => manufacturing[name] ?? fallback;
  return <><h2>Pass Detail</h2><div className="metrics"><Metric label="Width" value={metric("profile_width", pass.width)} /><Metric label="Height" value={metric("maximum_profile_height", pass.height)} /><Metric label="Developed length" value={metric("neutral_line_developed_length", pass.generated_neutral_length)} /><Metric label="Aspect ratio" value={pass.features ? (pass.features as any).geometry?.bbox?.aspect_ratio : null} /><Metric label="Active bends" value={metric("active_bend_count", pass.physical_forming_bend_count)} /><Metric label="Total bend angle" value={metric("total_absolute_bend_angle", pass.physical_total_bend_angle)} /><Metric label="Min R/t" value={metric("minimum_radius_to_thickness")} /><Metric label="Symmetry score" value={metric("symmetry_score")} /><Metric label="Bend density" value={metric("bend_density")} /><Metric label="Formedness index" value={metric("formedness_index")} /><Metric label="Feature confidence" value={quality?.confidence} /><Metric label="Schema version" value={pass.feature_schema_version} /></div><p>Units: {quality?.units_status ?? "UNKNOWN"}</p>{quality?.flags?.map((flag) => <p key={flag}><strong>Quality warning:</strong> {flag}</p>)}<div className="links">{Object.entries(pass.feature_downloads ?? {}).filter(([, path]) => path).map(([name, path]) => <a key={name} href={artifactUrl(projectId, path as string)}>{name}</a>)}</div><BendTable pass={pass} /></>;
}

function WhatChanged({ changes }: { changes: StepChange[] }) {
  return <><h2>What Changed</h2><table><tbody>{changes.map((c) => <tr key={`${c.from_pass_id}-${c.to_pass_id}`}><td>{c.from_pass_id} → {c.to_pass_id}</td><td>{c.summary}</td><td>{c.review_choices?.join(" | ")}</td></tr>)}</tbody></table></>;
}

function BendProgression({ flower }: { flower?: CompositeFlower }) {
  const ids = useMemo(() => Array.from(new Set((flower?.passes ?? []).flatMap((p) => p.bend_zones.map((z) => z.bend_id)))).sort(), [flower]);
  return <><h2>Bend-Zone Progression</h2><table><thead><tr><th>Zone</th>{flower?.passes.map((p) => <th key={p.pass_id}>{p.name}</th>)}</tr></thead><tbody>{ids.map((id) => <tr key={id}><td>{id}</td>{flower?.passes.map((p) => <td key={p.pass_id}>{p.bend_zones.find((z) => z.bend_id === id)?.signed_bend_angle ?? 0}</td>)}</tr>)}</tbody></table></>;
}

function BendTable({ pass }: { pass?: FlowerPass }) {
  return <table><thead><tr><th>Zone</th><th>u</th><th>angle</th><th>length</th><th>vertices</th></tr></thead><tbody>{pass?.bend_zones.map((z) => <tr key={z.bend_id}><td>{z.bend_id}</td><td>{z.u?.toFixed(3)}</td><td>{z.signed_bend_angle}</td><td>{z.zone_length?.toFixed?.(3)}</td><td>{z.contributing_vertex_count}</td></tr>)}</tbody></table>;
}

function Warnings({ report }: { report: ReportData | null }) {
  return <><h2>Warnings</h2>{(report?.warnings ?? []).map((w) => <p key={`${w.code}-${w.message}`}><strong>{w.code}</strong> {w.message}</p>)}</>;
}

function EngineerReview({ onExport, onApplyUnits, flower }: { onExport: () => void; onApplyUnits: () => void; flower?: CompositeFlower }) {
  return <><h2>Engineer Review</h2><button onClick={onExport}>Export Review Decisions</button><button onClick={onApplyUnits}>Confirm units as mm</button><p>Controls cover units, pass count/order, pass exclusion, reference classification, thickness, neutral lines, merge/split/rename bend zones, Pass 03→Pass 04 anomaly choices, transition confirmation, and comments.</p>{flower?.profile_step_changes.filter((c) => c.review_choices?.length).map((c) => <fieldset key={`${c.from_pass_id}-${c.to_pass_id}`}><legend>{c.from_pass_id} → {c.to_pass_id}</legend>{c.review_choices?.map((choice) => <label key={choice}><input type="radio" name={`${c.from_pass_id}-${c.to_pass_id}`} />{choice}</label>)}</fieldset>)}</>;
}

function Exports({ projectId, artifacts }: { projectId: string; artifacts: Record<string, { sha256: string }> }) {
  return <><h2>Exports</h2><div className="links">{Object.keys(artifacts).map((path) => <a key={path} href={artifactUrl(projectId, path)}>{path}</a>)}</div></>;
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return <div className="metric"><strong>{String(value ?? "-")}</strong><span>{label}</span></div>;
}
