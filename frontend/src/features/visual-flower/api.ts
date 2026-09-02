import type { CadDrawingPreview, VisualProfile, VisualRun } from "./types";

const API_ROOT = import.meta.env.VITE_API_ROOT ?? "";
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, init);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}
export const createVisualTarget = (profile: VisualProfile) =>
  request<{ target_id: string }>("/api/visual-flower/targets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: profile.name, profile }),
  });
export const generateVisualFlower = (
  targetId: string,
  preferences: Record<string, unknown>,
) =>
  request<VisualRun>(
    `/api/visual-flower/targets/${encodeURIComponent(targetId)}/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(preferences),
    },
  );
export const getVisualDatasetStatus = () =>
  request<
    {
      available: boolean;
      flower_count: number;
      pass_count: number;
      dataset_hash: string;
      warning?: string;
    }
  >("/api/visual-flower/dataset-status");
export const getVisualModelStatus = () =>
  request<
    {
      algorithm_version: string;
      active_models: Array<
        { model_id: string; status: string; privacy_classification: string }
      >;
      deterministic_fallback: boolean;
      production_approval: string;
    }
  >("/api/visual-flower/model/status");
export const getVisualModelDoctor = () =>
  request<
    {
      status: string;
      checks: Record<string, boolean>;
      model?: Record<string, unknown>;
      deterministic_fallback: boolean;
      private_paths_redacted: boolean;
      production_approval: string;
    }
  >("/api/visual-flower/model/doctor");
export const reviewVisualCandidate = (
  candidateId: string,
  body: {
    decision: string;
    reviewer: string;
    reason_codes: string[];
    notes?: string;
  },
) =>
  request(
    `/api/visual-flower/candidates/${encodeURIComponent(candidateId)}/review`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
export async function importVisualCad(
  file: File,
): Promise<
  {
    import_id: string;
    visual_import_id: string;
    project_id?: string;
    analysis_job_id?: string;
    source_sha256?: string;
    workflow_id?: string;
    status: string;
    profile_count: number;
    converter?: string;
    error?: string;
  }
> {
  const body = new FormData();
  body.append("file", file);
  return request("/api/rollform-workflows/import", { method: "POST", body });
}
export const getVisualImportProfiles = (importId: string) =>
  request<
    Array<
      {
        profile_id: string;
        profile?: VisualProfile;
        open_closed: string;
        entity_count: number;
        width?: number;
        height?: number;
        source_layers?: string[];
        source_units?: string | null;
        unit_status?: string;
        aspect_ratio: number | null;
        warnings: string[];
        thumbnail_svg: string;
      }
    >
  >(`/api/visual-flower/imports/${encodeURIComponent(importId)}/profiles`);
export const getVisualImportProfile = (importId: string, profileId: string) =>
  request<{ profile_id: string; profile: VisualProfile; warnings: string[] }>(
    `/api/visual-flower/imports/${encodeURIComponent(importId)}/profiles/${encodeURIComponent(profileId)}`,
  );
export const getVisualImportDrawingPreview = (importId: string) =>
  request<CadDrawingPreview>(`/api/visual-flower/imports/${encodeURIComponent(importId)}/drawing-preview`);

export const getHistoricalFlowers = () =>
  request<{ schema_version: number; dataset_hash?: string; flowers: Array<{ flower_id: string; station_count: number; topology?: string; quality_flags: string[] }>; private_paths_redacted: boolean }>(
    "/api/visual-flower/historical/flowers",
  );

export const getHistoricalFlower = (flowerId: string) =>
  request<{ flower_id: string; station_count: number; passes: Array<Record<string, unknown>>; private_paths_redacted: boolean }>(
    `/api/visual-flower/historical/flowers/${encodeURIComponent(flowerId)}`,
  );

export const getHistoricalPass = (flowerId: string, passId: string) =>
  request<Record<string, unknown>>(
    `/api/visual-flower/historical/flowers/${encodeURIComponent(flowerId)}/passes/${encodeURIComponent(passId)}`,
  );
export const validateVisualProfile = (profile: VisualProfile) =>
  request<{ valid: boolean; profile_hash: string; blocking_errors: Array<{ code: string; message: string }>; warnings: string[]; checks: Record<string, boolean>; normalized_profile?: VisualProfile }>("/api/visual-flower/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile }) });
export const generateRollformWorkflow = (workflowId: string, preferences: Record<string, unknown>) =>
  request<VisualRun>(`/api/rollform-workflows/${encodeURIComponent(workflowId)}/generate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(preferences) });
export const synchronizeWorkflowTarget = (workflowId: string, profile: VisualProfile) =>
  request<{ workflow: Record<string, unknown>; target: { target_id: string; profile: VisualProfile } }>(`/api/rollform-workflows/${encodeURIComponent(workflowId)}/target`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile }) });
export const useVisualImportProfile = (importId: string, profileId: string) =>
  request<{ target_id: string; profile: VisualProfile }>(
    `/api/visual-flower/imports/${encodeURIComponent(importId)}/profiles/${
      encodeURIComponent(profileId)
    }/use`,
    { method: "POST" },
  );
export const useWorkflowImportProfile = (workflowId: string, profileId: string) =>
  request<{ target: { target_id: string; profile: VisualProfile } }>(
    `/api/rollform-workflows/${encodeURIComponent(workflowId)}/profiles/${encodeURIComponent(profileId)}/select`,
    { method: "POST" },
  );
export const reviewRollerEvidence = (candidateId: string, passId: string, body: { role: string; decision: string; reviewer: string; selected_design_id?: string; selected_revision_id?: string | null; selected_source_reference_id?: string | null; notes?: string }) =>
  request(`/api/visual-flower/candidates/${encodeURIComponent(candidateId)}/passes/${encodeURIComponent(passId)}/roller-evidence/review`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
export function visualExportUrl(candidateId: string, artifact: string): string {
  return `${API_ROOT}/api/visual-flower/candidates/${
    encodeURIComponent(candidateId)
  }/export/${artifact}`;
}
