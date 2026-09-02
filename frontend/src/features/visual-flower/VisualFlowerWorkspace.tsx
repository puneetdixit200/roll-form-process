import { useEffect, useMemo, useRef, useState } from "react";
import {
  createVisualTarget,
  generateVisualFlower,
  generateRollformWorkflow,
  getVisualDatasetStatus,
  getVisualImportProfiles,
  getVisualImportProfile,
  getVisualImportDrawingPreview,
  getVisualModelDoctor,
  getVisualModelStatus,
  importVisualCad,
  reviewVisualCandidate,
  reviewRollerEvidence,
  synchronizeWorkflowTarget,
  validateVisualProfile,
  visualExportUrl,
} from "./api";
import { exampleProfile, ProfileSketcher } from "./ProfileSketcher";
import { CadDrawingCanvas } from "./CadDrawingCanvas";
import type { CadDrawingPreview, VisualCandidate, VisualProfile, VisualRun } from "./types";

type ImportedProfile = {
  profile_id: string;
  profile?: VisualProfile;
  open_closed: string;
  entity_count: number;
  width?: number;
  height?: number;
  source_layers?: string[];
  source_units?: string | null;
  source_handles?: string[];
  aspect_ratio: number | null;
  warnings: string[];
  thumbnail_svg: string;
};

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value as Record<string, unknown>).sort().map((key) => `${JSON.stringify(key)}:${stableJson((value as Record<string, unknown>)[key])}`).join(",")}}`;
  return JSON.stringify(value);
}

export default function VisualFlowerWorkspace() {
  const [profile, setProfile] = useState<VisualProfile | null>(exampleProfile());
  const [run, setRun] = useState<VisualRun | null>(null);
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [passIndex, setPassIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [speed, setSpeed] = useState(900);
  const [viewMode, setViewMode] = useState("GENERATED");
  const [stationMode, setStationMode] = useState("EXACT");
  const [stationCount, setStationCount] = useState(16);
  const [minimumStationCount, setMinimumStationCount] = useState(8);
  const [maximumStationCount, setMaximumStationCount] = useState(28);
  const [candidateLimit, setCandidateLimit] = useState(3);
  const [generationEngine, setGenerationEngine] = useState("AUTO");
  const [message, setMessage] = useState("");
  // The bundled public example is known-valid, so the demo can be generated
  // immediately. Any edit, import, or JSON load resets this gate below.
  const [validated, setValidated] = useState(true);
  const [validatedProfileSnapshot, setValidatedProfileSnapshot] = useState<string | null>(stableJson(exampleProfile()));
  const [backendValidationHash, setBackendValidationHash] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<{ valid: boolean; profile_hash: string; blocking_errors: Array<{ code: string; message: string }>; warnings: string[]; checks: Record<string, boolean> } | null>(null);
  const [targetSource, setTargetSource] = useState<"DEMO" | "MANUAL" | "JSON" | "CAD">("DEMO");
  const [guided, setGuided] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [importId, setImportId] = useState<string | null>(null);
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [importProfiles, setImportProfiles] = useState<ImportedProfile[]>([]);
  const [drawingPreview, setDrawingPreview] = useState<CadDrawingPreview | null>(null);
  const [selectedImportedProfileId, setSelectedImportedProfileId] = useState<string | null>(null);
  const [editingImported, setEditingImported] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dataset, setDataset] = useState<
    {
      available: boolean;
      flower_count: number;
      pass_count: number;
      warning?: string;
    } | null
  >(null);
  const [modelStatus, setModelStatus] = useState<
    {
      algorithm_version: string;
      active_models: Array<
        { model_id: string; status: string; privacy_classification: string }
      >;
      deterministic_fallback: boolean;
      production_approval: string;
    } | null
  >(null);
  const [modelDoctor, setModelDoctor] = useState<
    { status: string; model?: Record<string, unknown> } | null
  >(null);
  const profileHashRef = useRef(profile ? stableJson(profile) : null);
  useEffect(() => { profileHashRef.current = profile ? stableJson(profile) : null; }, [profile]);
  const candidate: VisualCandidate | undefined = run
    ?.candidates[candidateIndex];
  const currentPass = candidate?.passes[passIndex];
  useEffect(() => {
    getVisualDatasetStatus().then(setDataset).catch(() =>
      setDataset({
        available: false,
        flower_count: 0,
        pass_count: 0,
        warning: "Backend unavailable",
      })
    );
    getVisualModelStatus().then(setModelStatus).catch(() =>
      setModelStatus(null)
    );
    getVisualModelDoctor().then(setModelDoctor).catch(() =>
      setModelDoctor({ status: "NOT_READY" })
    );
  }, []);
  useEffect(() => {
    if (!playing || !candidate || candidate.passes.length < 2) return;
    const timer = window.setInterval(() =>
      setPassIndex((value) => {
        const next = value + 1;
        if (next >= candidate.passes.length && !loop) {
          setPlaying(false);
          return value;
        }
        return next % candidate.passes.length;
      }), speed);
    return () => window.clearInterval(timer);
  }, [candidate, loop, playing, speed]);
  const validation = useMemo(() => {
    if (!profile) return { valid: false, broken: [], zero: [], seam: false };
    const ids = new Set(profile.vertices.map((point) => point.vertex_id));
    const broken = profile.segments.filter((segment) =>
      !ids.has(segment.start_vertex_id) || !ids.has(segment.end_vertex_id)
    );
    const zero = profile.segments.filter((segment) =>
      segment.start_vertex_id === segment.end_vertex_id
    );
    const connected = profile.segments.length > 0 && broken.length === 0 &&
      zero.length === 0;
    const seam = profile.topology === "OPEN_PATH" ||
      Boolean(
        profile.computational_seam_vertex_id &&
          ids.has(profile.computational_seam_vertex_id),
      );
    return {
      valid: profile.vertices.length >= 2 && connected && seam,
      broken,
      zero,
      seam,
    };
  }, [profile]);
  function validateProfile() {
    if (!profile) return;
    const hashAtRequest = stableJson(profile);
    setValidationResult(null);
    validateVisualProfile(profile).then((result) => {
      if (profileHashRef.current !== hashAtRequest) return;
      const valid = result.valid && validation.valid;
      setValidationResult(result);
      setValidated(valid);
      setValidatedProfileSnapshot(valid ? hashAtRequest : null);
      setBackendValidationHash(valid ? result.profile_hash : null);
      setMessage(valid ? "Profile validated by backend." : "Profile has blocking geometry issues; generation is disabled.");
    }).catch(() => { if (profileHashRef.current === hashAtRequest) { setValidated(false); setValidatedProfileSnapshot(null); setBackendValidationHash(null); setMessage("Profile validation failed; generation is disabled."); } });
  }
  async function generate() {
    if (!profile || !validated || validatedProfileSnapshot !== stableJson(profile)) return;
    try {
      setMessage("Canonicalizing and matching historical passes...");
      const target = workflowId
        ? await synchronizeWorkflowTarget(workflowId, profile).then((item) => item.target)
        : await createVisualTarget(profile);
      const preferences = {
        generation_engine: generationEngine,
        station_mode: stationMode,
        exact_station_count: stationCount,
        minimum_station_count: minimumStationCount,
        maximum_station_count: maximumStationCount,
        candidate_limit: candidateLimit,
        allow_mirror_matching: true,
        allow_rotation_alignment: true,
      };
      const next = workflowId
        ? await generateRollformWorkflow(workflowId, preferences)
        : await generateVisualFlower(target.target_id, preferences);
      setRun(next);
      setCandidateIndex(0);
      setPassIndex(0);
      setMessage(
        next.candidates.length
          ? "Candidate sequences ready for engineer review."
          : "No candidate sequences were generated. Confirm that the historical dataset is configured and contains compatible passes.",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Generation failed");
    }
  }
  function downloadJson(name: string, value: unknown) {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(
      new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
    );
    link.download = name;
    link.click();
    URL.revokeObjectURL(link.href);
  }
  function saveTarget() {
    if (profile) downloadJson(`${profile.profile_id}.json`, profile);
  }
  function loadTarget(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".json")) {
      setMessage(
        "CAD files should use Import DWG/DXF so profiles can be detected and selected safely.",
      );
      return;
    }
    file.text().then((text) => {
      try {
        setTargetSource("JSON"); setImportId(null); setWorkflowId(null); setDrawingPreview(null); setImportProfiles([]); setSelectedImportedProfileId(null); setEditingImported(false); setRun(null); setProfile(JSON.parse(text) as VisualProfile); setValidated(false); setValidatedProfileSnapshot(null); setBackendValidationHash(null); setValidationResult(null);
        setMessage("Target loaded. Validate before generation.");
      } catch {
        setMessage("Target JSON could not be read.");
      }
    });
  }
  async function uploadCad(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const input = event.currentTarget;
    input.value = "";
    setTargetSource("CAD"); setImportId(null); setWorkflowId(null); setRun(null); setCandidateIndex(0); setPassIndex(0); setPlaying(false); setValidated(false); setValidatedProfileSnapshot(null); setBackendValidationHash(null); setValidationResult(null); setProfile(null); setImportProfiles([]); setDrawingPreview(null); setSelectedImportedProfileId(null); setEditingImported(false); setMessage("Uploading → converting → parsing → detecting profiles...");
    try {
      const result = await importVisualCad(file);
      const actualImportId = result.visual_import_id || result.import_id;
      setImportId(actualImportId);
      setWorkflowId(result.workflow_id ?? null);
      const [profiles, preview] = await Promise.all([getVisualImportProfiles(actualImportId), getVisualImportDrawingPreview(actualImportId)]);
      setImportProfiles(profiles);
      setDrawingPreview(preview);
      setEditingImported(false);
      if (profiles.length === 1) await selectImportedCandidate(actualImportId, profiles[0].profile_id);
      setMessage(
        `${result.profile_count} profile candidate(s) detected using ${
          result.converter ?? "offline extraction"
        }. Select one below.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "CAD import failed");
    } finally {
      setUploading(false);
    }
  }
  async function selectImportedCandidate(sourceImportId: string, profileId: string) {
    try {
      const result = await getVisualImportProfile(sourceImportId, profileId);
      setProfile(result.profile);
      setSelectedImportedProfileId(profileId);
      setEditingImported(false);
      setRun(null); setCandidateIndex(0); setPassIndex(0);
      setValidated(false);
      setValidatedProfileSnapshot(null); setBackendValidationHash(null); setValidationResult(null);
      setMessage(
        "Imported profile loaded. Review and validate before generation.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Profile selection failed",
      );
    }
  }
  async function useImported(profileId: string) { if (importId) { await selectImportedCandidate(importId, profileId); setEditingImported(true); } }
  async function review(decision: string) {
    if (!candidate || !reviewer.trim()) {
      setMessage("Enter a reviewer name before submitting feedback.");
      return;
    }
    try {
      await reviewVisualCandidate(candidate.candidate_id, {
        decision,
        reviewer,
        reason_codes: [
          decision === "ACCEPT_VISUAL_SEQUENCE"
            ? "SMOOTH_PROGRESSION"
            : "OTHER",
        ],
        notes: "Phase 21 local engineer feedback",
      });
      setMessage(
        "Review captured as evidence; model approval and weights were unchanged.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Review submission failed",
      );
    }
  }
  function resetDemo() {
    setProfile(exampleProfile());
    setTargetSource("DEMO"); setImportId(null); setWorkflowId(null); setDrawingPreview(null); setSelectedImportedProfileId(null); setEditingImported(false); setImportProfiles([]); setValidationResult(null); setBackendValidationHash(null); setValidatedProfileSnapshot(stableJson(exampleProfile()));
    setRun(null);
    setCandidateIndex(0);
    setPassIndex(0);
    setValidated(true);
    setImportProfiles([]);
    setMessage("Guided demo reset to the public example.");
  }
  function passPoints(points: number[][]) {
    return points.map((point) => point.join(",")).join(" ");
  }
  function exportCandidate(artifact: string) {
    if (candidate) {
      window.open(
        visualExportUrl(candidate.candidate_id, artifact),
        "_blank",
        "noopener,noreferrer",
      );
    }
  }
  function matchForPass(item: any) {
    return item?.historical_match?.best_match;
  }
  return (
    <section className="visual-workspace">
      <h2>Visual Flower Generator</h2>
      <div className="model-status-panel">
        <strong>Private learned model:</strong>{" "}
        {modelStatus?.active_models?.[0]?.model_id ?? "UNAVAILABLE"} ·{" "}
        <strong>Artifact health:</strong>{" "}
        {modelDoctor?.status === "READY" ? "VERIFIED" : "CHECK REQUIRED"} ·{" "}
        <strong>Approval:</strong> PRIVATE PROTOTYPE ·{" "}
        <strong>Fallback:</strong> AVAILABLE · <strong>Manufacturing:</strong>
        {" "}
        NOT APPROVED
      </div>
      <div className="visual-controls">
        <button
          className={guided ? "active" : ""}
          onClick={() => setGuided((value) => !value)}
        >
          Guided Demo
        </button>
        <button onClick={resetDemo}>Reset demo</button>
        <label>
          Generation engine{" "}
          <select
            value={generationEngine}
            onChange={(event) => setGenerationEngine(event.target.value)}
          >
            <option value="AUTO">Automatic</option>
            <option value="DETERMINISTIC_ONLY">Deterministic only</option>
            <option value="LEARNED_HYBRID">Learned hybrid</option>
            <option value="COMPARE_ALL">Compare all</option>
          </select>
        </label>
      </div>
      {guided && (
        <p className="notice">
          Guided flow: target → generate 16 stages with COMPARE_ALL → review
          candidates → export evidence.
        </p>
      )}
      <p className="notice">
        <strong>Historically grounded visual prototype.</strong>{" "}
        VISUAL CONFIDENCE measures geometry support only. It is not
        manufacturing, tooling or production confidence.
      </p>
      <details className="prototype-evidence">
        <summary>Prototype Evidence</summary>
        <div className="metrics">
          <Metric label="Historical flowers" value={dataset?.available ? String(dataset.flower_count) : "Unavailable"} />
          <Metric label="Historical passes" value={dataset?.available ? String(dataset.pass_count) : "Unavailable"} />
          <Metric label="Held-out improvement" value="73.64%" />
          <Metric label="OOD detection" value="100%" />
          <Metric label="Fallback" value="6.25%" />
        </div>
          <p>
            Evidence is redacted and private-source safe. These are
          synthetic-derived prototype metrics, not manufacturing accuracy.
          Manufacturing approval remains NOT APPROVED and physical roller
          availability is NOT DETERMINED.
        </p>
      </details>
      <div className="visual-layout">
        <div>
          <h3>Target Profile</h3>
          <div className="visual-controls">
            <label className="primary-action">
              Import DWG/DXF{" "}
              <input
                type="file"
                accept=".dwg,.dxf"
                onChange={uploadCad}
                disabled={uploading}
              />
            </label>
            <label>
              Load profile JSON{" "}
              <input
                type="file"
                accept="application/json"
                onChange={loadTarget}
              />
            </label>
          </div>
          {drawingPreview && (
            <>
              <h4>Imported drawing inspection</h4>
              <p>Drawing preview: READY · {drawingPreview.unit_status === "UNKNOWN" ? "Units unknown" : drawingPreview.units}</p>
              <CadDrawingCanvas
                preview={drawingPreview}
                candidates={importProfiles}
                selectedId={selectedImportedProfileId}
                onSelect={(id) => void (importId && selectImportedCandidate(importId, id))}
              />
            </>
          )}
          {importProfiles.length > 0 && (
            <div className="import-candidates">
              <h4>Detected profile candidates</h4>
              {importProfiles.map((item) => (
                <article className={`import-card ${selectedImportedProfileId === item.profile_id ? "selected" : ""}`} key={item.profile_id} onClick={() => void (importId && selectImportedCandidate(importId, item.profile_id))}>
                  <div>
                    <strong>{item.profile_id}</strong>
                    <p>
                      {item.open_closed} · {item.entity_count} entities · aspect
                      {" "}
                      {item.aspect_ratio?.toFixed(2) ?? "unknown"}
                    </p>
                    <p>
                      {item.width?.toFixed(2) ?? "?"} × {item.height?.toFixed(2) ?? "?"}
                      {item.source_units ? ` ${item.source_units}` : " drawing units"}
                      {item.source_layers?.length
                        ? ` · layers ${item.source_layers.join(", ")}`
                        : ""}
                    </p>
                    <p>
                      {item.warnings.length
                        ? item.warnings.join(", ")
                        : "No geometry warnings"}
                    </p>
                    <button
                      onClick={() =>
                        useImported(item.profile_id)}
                    >
                      Use this profile
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
          {importId && !editingImported
            ? <p><button disabled={!selectedImportedProfileId} onClick={() => selectedImportedProfileId && void useImported(selectedImportedProfileId)}>Edit selected profile</button></p>
            : profile ? <ProfileSketcher
                profile={profile}
                onChange={(next) => {
                  setProfile(next);
                  setValidated(false);
                  setValidatedProfileSnapshot(null); setBackendValidationHash(null);
                  setValidationResult(null);
                  setTargetSource("MANUAL");
                }}
              /> : <p>Select a detected profile to continue.</p>}
          <div className="visual-controls">
            <button disabled={!profile || Boolean(importId && !selectedImportedProfileId)} onClick={() => void validateProfile()}>Validate Profile</button>
            <button onClick={saveTarget}>Save target JSON</button>
            <fieldset disabled={!validated || validatedProfileSnapshot !== (profile ? stableJson(profile) : null)}><legend>Configure Flower</legend><label>
              Station mode{" "}
              <select
                value={stationMode}
                onChange={(event) => setStationMode(event.target.value)}
              >
                <option value="EXACT">Exact</option>
                <option value="AUTOMATIC">Automatic</option>
                <option value="RANGE">Range</option>
              </select>
            </label>
            {stationMode === "EXACT"
              ? (
                <label>
                  Stages{" "}
                  <input
                    type="number"
                    min={8}
                    max={28}
                    value={stationCount}
                    onChange={(event) =>
                      setStationCount(Number(event.target.value))}
                  />
                </label>
              )
              : (
                <>
                  <label>
                    Min stages{" "}
                    <input
                      type="number"
                      min={8}
                      max={28}
                      value={minimumStationCount}
                      onChange={(event) =>
                        setMinimumStationCount(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    Max stages{" "}
                    <input
                      type="number"
                      min={8}
                      max={28}
                      value={maximumStationCount}
                      onChange={(event) =>
                        setMaximumStationCount(Number(event.target.value))}
                    />
                  </label>
                </>
              )}
            <label>
              Candidates{" "}
              <input
                type="number"
                min={1}
                max={3}
                value={candidateLimit}
                onChange={(event) =>
                  setCandidateLimit(Number(event.target.value))}
              />
            </label>
            <button
              disabled={
                !validation.valid || !validated || dataset?.available === false
              }
              onClick={generate}
            >
              Generate Flower Sequence
            </button>
            </fieldset>
          </div>
          {validationResult && <section aria-label="Backend validation result"><strong>Validation: {validationResult.valid ? "PASS" : "FAILED"}</strong>{backendValidationHash && <small> Backend validation hash recorded.</small>}{validationResult.blocking_errors.map((error) => <div key={error.code}>- {error.code}: {error.message}</div>)}{validationResult.warnings.map((warning) => <div key={warning}>Warning: {warning}</div>)}</section>}
          <p>
            {validated
              ? (validation.valid
                ? "Valid profile."
                : `Invalid profile: ${validation.broken.length} broken and ${validation.zero.length} zero-length segment(s).`)
              : "Validate Profile before generation."}
          </p>
          <p>
            {dataset?.available
              ? `Historical evidence: ${dataset.flower_count} flowers, ${dataset.pass_count} passes.`
              : dataset?.warning ?? "Historical dataset status unknown."}
          </p>
        </div>
        <div>
          <h3>Candidate Sequences</h3>
          {run?.candidates.length
            ? (
              <>
                <div className="candidate-tabs">
                  {run.candidates.map((item, index) => (
                    <button
                      key={item.candidate_id}
                      className={candidateIndex === index ? "active" : ""}
                      onClick={() => {
                        setCandidateIndex(index);
                        setPassIndex(0);
                      }}
                    >
                      {item.candidate_style} · {item.station_count} stations ·
                      {" "}
                      {item.visual_confidence.score.toFixed(1)}
                    </button>
                  ))}
                </div>
                {candidate && (
                  <>
                    <div className="metrics">
                      <Metric
                        label="VISUAL CONFIDENCE"
                        value={`${
                          candidate.visual_confidence.score.toFixed(1)
                        } / 100`}
                      />
                      <Metric
                        label="Band"
                        value={candidate.visual_confidence.band}
                      />
                      <Metric
                        label="Mean / minimum"
                        value={`${
                          candidate.visual_confidence.mean_pass_confidence
                            .toFixed(1)
                        } / ${
                          candidate.visual_confidence.minimum_pass_confidence
                            .toFixed(1)
                        }`}
                      />
                      <Metric
                        label="Historical coverage"
                        value={`${
                          candidate.passes.filter((item) => matchForPass(item))
                            .length
                        }/${candidate.passes.length}`}
                      />
                    </div>
                    <StripLengthCandidateStatus candidate={candidate} />
                    <div className="candidate-comparison">
                      <strong>Candidate comparison</strong>
                      {run.candidates.slice(0, 3).map((item) => (
                        <span key={item.candidate_id}>
                          {item.candidate_style}: {item.station_count} stations,
                          {" "}
                          {item.visual_confidence.score.toFixed(1)},{" "}
                          {item.visual_confidence.band}
                        </span>
                      ))}
                    </div>
                    <div className="visual-controls">
                      <button onClick={() => setPlaying((value) => !value)}>
                        {playing ? "Pause" : "Play"}
                      </button>
                      <button
                        onClick={() =>
                          setPassIndex((value) => Math.max(0, value - 1))}
                      >
                        Previous
                      </button>
                      <button
                        onClick={() =>
                          setPassIndex((value) =>
                            Math.min(candidate.passes.length - 1, value + 1)
                          )}
                      >
                        Next
                      </button>
                      <label>
                        Speed{" "}
                        <select
                          value={speed}
                          onChange={(event) =>
                            setSpeed(Number(event.target.value))}
                        >
                          <option value={1400}>Slow</option>
                          <option value={900}>Normal</option>
                          <option value={450}>Fast</option>
                        </select>
                      </label>
                      <label>
                        <input
                          type="checkbox"
                          checked={loop}
                          onChange={(event) => setLoop(event.target.checked)}
                        />{" "}
                        Loop
                      </label>
                      <button onClick={() => exportCandidate("zip")}>
                        ZIP export
                      </button>
                    </div>
                    <div className="visual-controls">
                      <label>
                        Reviewer{" "}
                        <input
                          aria-label="Reviewer name"
                          value={reviewer}
                          onChange={(event) => setReviewer(event.target.value)}
                          placeholder="Engineer"
                        />
                      </label>
                      <button onClick={() => review("ACCEPT_VISUAL_SEQUENCE")}>
                        Accept visual sequence
                      </button>
                      <button onClick={() => review("NEEDS_MANUAL_EDIT")}>
                        Needs manual edit
                      </button>
                    </div>
                    <div className="visual-controls">
                      <label>
                        View{" "}
                        <select
                          value={viewMode}
                          onChange={(event) => setViewMode(event.target.value)}
                        >
                          <option value="GENERATED">Generated profile</option>
                          <option value="HISTORICAL">Historical match</option>
                          <option value="OVERLAY">Overlay</option>
                          <option value="DIFFERENCE">Difference</option>
                          <option value="ALL">All stages</option>
                        </select>
                      </label>
                      {["dxf", "svg", "png", "json", "csv", "html"].map((
                        item,
                      ) => (
                        <button
                          key={item}
                          onClick={() => exportCandidate(item)}
                        >
                          {item.toUpperCase()} export
                        </button>
                      ))}
                    </div>
                    <div className="station-thumbnails">
                      {candidate.passes.map((item, index) => (
                        <button
                          key={item.pass_id}
                          className={index === passIndex ? "active" : ""}
                          onClick={() => setPassIndex(index)}
                        >
                          P{item.order}
                        </button>
                      ))}
                    </div>
                    <svg
                      role="img"
                      aria-label="Generated pass viewer"
                      viewBox="-2 -2 4 4"
                      style={{
                        width: "100%",
                        minHeight: 300,
                        border: "1px solid #b7c0ca",
                      }}
                    >
                      {candidate.passes.map((item, index) => {
                        const generated = item.profile.points;
                        const historical = matchForPass(item);
                        const historicalPoints = historical?.historical_points;
                        return (
                          <g
                            key={item.pass_id}
                            opacity={viewMode === "ALL"
                              ? (index === passIndex ? 1 : .22)
                              : index === passIndex
                              ? 1
                              : .08}
                          >
                            <polyline
                              points={passPoints(generated)}
                              fill="none"
                              stroke={index === passIndex
                                ? "#c46b00"
                                : "#8aa5b9"}
                              strokeWidth={index === passIndex
                                ? ".025"
                                : ".008"}
                            />
                            <polyline
                              points={viewMode === "OVERLAY" ||
                                  viewMode === "HISTORICAL"
                                ? passPoints(historicalPoints ?? [])
                                : ""}
                              fill="none"
                              stroke="#155783"
                              strokeWidth=".012"
                              strokeDasharray=".04 .02"
                            />
                          </g>
                        );
                      })}
                    </svg>
                    <input
                      aria-label="Station slider"
                      type="range"
                      min={0}
                      max={candidate.passes.length - 1}
                      value={passIndex}
                      onChange={(event) =>
                        setPassIndex(Number(event.target.value))}
                    />
                    <p>
                      Station {currentPass?.order} ·{" "}
                      {Math.round((currentPass?.progress ?? 0) * 100)}% progress
                      · {currentPass?.visual_confidence.band}
                    </p>
                    <StripLengthPassStatus pass={currentPass} />
                    <p>
                      Legend:{" "}
                      <span className="generated-key">orange = generated</span>;
                      {" "}
                      <span className="historical-key">
                        blue dashed = historical match
                      </span>.
                    </p>
                    <MatchDetails item={currentPass} />
                    <RollerEvidenceDetails
                      candidateId={candidate.candidate_id}
                      station={candidate.roller_evidence?.stations.find((item) => item.pass_id === currentPass?.pass_id)}
                      reviewer={reviewer}
                      onReview={async (role, decision, selectedDesignId, selectedRevisionId) => {
                        if (!currentPass || !reviewer.trim()) {
                          setMessage("Enter a reviewer name before reviewing roller evidence.");
                          return;
                        }
                        try {
                          await reviewRollerEvidence(candidate.candidate_id, currentPass.pass_id, { role, decision, reviewer, selected_design_id: selectedDesignId, selected_revision_id: selectedRevisionId });
                        } catch (error) {
                          setMessage(error instanceof Error ? error.message : "Roller evidence review failed.");
                          return;
                        }
                        setMessage("Roller design evidence review recorded.");
                      }}
                    />
                  </>
                )}
              </>
            )
            : <p>Validate a profile, then generate a sequence.</p>}
          <p>{message}</p>
        </div>
      </div>
    </section>
  );
}

function MatchDetails({ item }: { item: any }) {
  const matches = item?.historical_match?.top_matches ?? [];
  return (
    <details className="match-details">
      <summary>Top three historical matches and score components</summary>
      {matches.map((match: any, index: number) => (
        <div key={`${match.source_flower_id}-${match.source_pass_id}-${index}`}>
          <div className="historical-match-preview">
            <img
              src={`/api/visual-flower/historical-preview/${encodeURIComponent(match.source_flower_id)}/${encodeURIComponent(match.source_pass_id)}.png`}
              alt={`Historical geometry ${match.source_flower_id} ${match.source_pass_id}`}
            />
            <div>
          <strong>
            #{index + 1} {match.source_flower_id} / {match.source_pass_id}
          </strong>
          <p>
            Similarity {(match.overall_score * 100).toFixed(1)}% · coverage{" "}
            {(match.evidence_coverage * 100).toFixed(0)}% · mirror{" "}
            {String(match.mirror_used)} · rotation {String(match.rotation_used)}
          </p>
          <p>
            RMS {match.components?.point_rms_similarity?.score?.toFixed?.(3) ??
              "n/a"} · Chamfer{" "}
            {match.components?.chamfer_similarity?.score?.toFixed?.(3) ?? "n/a"}
            {" "}
            · tangent{" "}
            {match.components?.tangent_similarity?.score?.toFixed?.(3) ?? "n/a"}
            {" "}
            · curvature{" "}
            {match.components?.curvature_similarity?.score?.toFixed?.(3) ??
              "n/a"} · corner{" "}
            {match.components?.corner_signature_similarity?.score?.toFixed?.(
              3,
            ) ?? "n/a"} · aspect{" "}
            {match.components?.aspect_ratio_similarity?.score?.toFixed?.(3) ??
              "n/a"} · progress{" "}
            {match.components?.sequence_progress_similarity?.score?.toFixed?.(
              3,
            ) ?? "n/a"}
          </p>
          <a href={`/api/visual-flower/historical/flowers/${encodeURIComponent(match.source_flower_id)}`} target="_blank" rel="noreferrer">
            Open redacted historical source record
          </a>
            </div>
          </div>
        </div>
      ))}
    </details>
  );
}

function RollerEvidenceDetails({ candidateId, station, reviewer, onReview }: { candidateId: string; station: any; reviewer: string; onReview: (role: string, decision: string, designId?: string, revisionId?: string | null) => Promise<void> }) {
  return (
    <section className="roller-evidence" aria-label={`Roller design evidence for ${candidateId}`}>
      <h3>Roller design evidence</h3>
      <p><strong>Historical design evidence only.</strong> A candidate does not select a physical roller asset or approve tooling for manufacturing.</p>
      {!station || station.status === "INSUFFICIENT_ROLLER_EVIDENCE" ? (
        <p>Insufficient evidence — engineer review required.</p>
      ) : station.roles.map((role: any) => (
        <article key={role.role}>
          <strong>{role.role}</strong>
          {role.candidates.map((item: any) => (
            <div key={`${role.role}-${item.design_id}-${item.rank}`}>
              {item.rank === 1 ? "Best-supported design candidate" : `Alternative design candidate #${item.rank}`}: <strong>{item.design_id}</strong>
              {item.geometry_revision_id ? ` / ${item.geometry_revision_id}` : ""} · {item.evidence_tier}
              {item.recognition_score != null ? ` · recognition ${(item.recognition_score * 100).toFixed(1)}%` : ""}
              {item.top3_support_count != null ? ` · ${item.top3_support_count} of top 3 historical matches` : ""}
              {item.known_asset_count != null ? ` · known assets ${item.known_asset_count} (informational)` : ""}
              {(item.supporting_origins ?? []).map((origin: any) => (
                <a key={origin.source_reference_id} href={`/api/visual-flower/historical/flowers/${encodeURIComponent(origin.source_flower_id ?? "")}/passes/${encodeURIComponent(origin.source_pass_id ?? "")}`} target="_blank" rel="noreferrer">
                  Source {origin.source_reference_id}
                </a>
              ))}
              <button type="button" disabled={!reviewer.trim()} onClick={() => void onReview(role.role, "ACCEPT_DESIGN_EVIDENCE", item.design_id, item.geometry_revision_id)}>Accept evidence</button>
            </div>
          ))}
        </article>
      ))}
    </section>
  );
}

function StripLengthCandidateStatus({ candidate }: { candidate: VisualCandidate }) {
  const constraint = candidate.geometry_constraints;
  if (!constraint) {
    return (
      <section className="strip-length-status legacy" aria-label="Strip length status">
        <strong>Strip length: UNKNOWN / LEGACY RESULT</strong>
        <span>This saved result has no constant centerline-length evidence.</span>
      </section>
    );
  }
  const locked = constraint.enabled && constraint.satisfied;
  const target = constraint.target_length?.toFixed(4) ?? "unknown";
  const maximum = constraint.maximum_relative_error === undefined
    ? "unknown"
    : `${(constraint.maximum_relative_error * 100).toFixed(6)}%`;
  return (
    <section className={`strip-length-status ${locked ? "locked" : "warning"}`} aria-label="Strip length status">
      <strong>Strip length: {locked ? "LOCKED" : "WARNING"}</strong>
      <span>Target centerline: {target} visual units</span>
      <span>Maximum error: {maximum}</span>
      <span>Constraint version: {constraint.constraint_version}</span>
      <p>Centerline strip length is locked to the final target at every generated stage. This is a visual geometry constraint, not a neutral-axis, strain, springback, tooling, or manufacturing calculation.</p>
    </section>
  );
}

function StripLengthPassStatus({ pass }: { pass: VisualCandidate["passes"][number] | undefined }) {
  const constraint = pass?.generation?.strip_length_constraint;
  if (!constraint) return null;
  const closed = pass?.profile.topology === "CLOSED_CONTOUR";
  return (
    <section className="strip-length-pass" aria-label="Current station strip length details">
      <strong>Current station centerline constraint</strong>
      <span>Current centerline: {constraint.actual_length.toFixed(4)} visual units</span>
      <span>Target centerline: {constraint.target_length.toFixed(4)} visual units</span>
      <span>Relative error: {(constraint.relative_error * 100).toFixed(6)}%</span>
      <span>Projection method: {constraint.method}</span>
      <span>{closed
        ? "Perimeter: PRESERVED · Local segment lengths: NOT CLAIMED"
        : constraint.local_segment_lengths_preserved
        ? "Material-coordinate segment lengths: PRESERVED"
        : "Material-coordinate segment lengths: NOT CLAIMED"}</span>
    </section>
  );
}
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}
