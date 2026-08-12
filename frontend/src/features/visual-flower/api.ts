import type { VisualProfile, VisualRun } from "./types";

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
    status: string;
    profile_count: number;
    converter?: string;
    error?: string;
  }
> {
  const body = new FormData();
  body.append("file", file);
  return request("/api/visual-flower/import", { method: "POST", body });
}
export const getVisualImportProfiles = (importId: string) =>
  request<
    Array<
      {
        profile_id: string;
        profile?: VisualProfile;
        open_closed: string;
        entity_count: number;
        aspect_ratio: number | null;
        warnings: string[];
        thumbnail_svg: string;
      }
    >
  >(`/api/visual-flower/imports/${encodeURIComponent(importId)}/profiles`);
export const useVisualImportProfile = (importId: string, profileId: string) =>
  request<{ target_id: string; profile: VisualProfile }>(
    `/api/visual-flower/imports/${encodeURIComponent(importId)}/profiles/${
      encodeURIComponent(profileId)
    }/use`,
    { method: "POST" },
  );
export function visualExportUrl(candidateId: string, artifact: string): string {
  return `${API_ROOT}/api/visual-flower/candidates/${
    encodeURIComponent(candidateId)
  }/export/${artifact}`;
}
