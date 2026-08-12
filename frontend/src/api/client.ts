import type { JobRecord, ProjectRecord, ReportData, UploadResult } from "../types/report";

const API_ROOT = import.meta.env.VITE_API_ROOT ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, init);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}

export async function uploadDrawing(file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  return request<UploadResult>("/api/projects", { method: "POST", body: form });
}

export const getProject = (projectId: string) => request<ProjectRecord>(`/api/projects/${projectId}`);
export const getJob = (jobId: string) => request<JobRecord>(`/api/jobs/${jobId}`);
export const getReportData = (projectId: string) => request<ReportData>(`/api/projects/${projectId}/report-data`);
export const getArtifacts = (projectId: string) => request<{ files: Record<string, { sha256: string }> }>(`/api/projects/${projectId}/artifacts`);

export async function applyReview(projectId: string, decisions: unknown): Promise<ProjectRecord> {
  return request<ProjectRecord>(`/api/projects/${projectId}/review-decisions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(decisions),
  });
}

export function artifactUrl(projectId: string, path: string): string {
  return `${API_ROOT}/api/projects/${projectId}/artifacts/${path}`;
}

export type InventoryStats = { designs: number; assets: number; geometry_revisions: number; aliases: number; import_batches: number; review_rows: number };
export type InventoryDesign = { design_id: string; name?: string; design_type?: string; manufacturer?: string; status: string; verified: boolean };
export const getInventoryStats = () => request<InventoryStats>("/api/inventory/stats");
export const getInventoryDesigns = () => request<InventoryDesign[]>("/api/inventory/designs");
export const validateInventory = (file: File) => { const form = new FormData(); form.append("file", file); return request<any>("/api/inventory/validate", { method: "POST", body: form }); };
export const importInventory = (file: File) => { const form = new FormData(); form.append("file", file); return request<any>("/api/inventory/import", { method: "POST", body: form }); };
export const inventoryExportUrl = () => `${API_ROOT}/api/inventory/export`;

export type RecognitionRun = { id: number; status: string; algorithm_version: string; occurrence_count: number; candidate_count: number; configuration_hash?: string };
export type RecognitionCandidate = { id: number; occurrence_id?: string; design_id: string; geometry_revision_id: string; rank: number; overall_score: number; confidence: number; evidence_coverage: number; candidate_status: string; components: Record<string, unknown>; hard_filters: Record<string, unknown>; explanation: Record<string, unknown> };
export const createRecognitionRun = (projectId: string, options: Record<string, unknown> = {}) => request<{ run_id: number; occurrence_count: number; candidate_count: number }>(`/api/projects/${projectId}/roller-recognition/runs`, { method: "POST", body: JSON.stringify(options), headers: { "Content-Type": "application/json" } });
export const getRecognitionRuns = (projectId: string) => request<RecognitionRun[]>(`/api/projects/${projectId}/roller-recognition/runs`);
export const getRecognitionCandidates = (projectId: string, runId: number) => request<RecognitionCandidate[]>(`/api/projects/${projectId}/roller-recognition/runs/${runId}/candidates`);
export const reviewRecognitionCandidate = (projectId: string, candidateId: number, decision: Record<string, unknown>) => request<{ review_id: number }>(`/api/projects/${projectId}/roller-recognition/candidates/${candidateId}/review`, { method: "POST", body: JSON.stringify(decision), headers: { "Content-Type": "application/json" } });
