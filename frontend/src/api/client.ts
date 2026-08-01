import type { JobRecord, ProjectRecord, ReportData, UploadResult } from "../types/report";

const API_ROOT = import.meta.env.VITE_API_ROOT ?? "http://127.0.0.1:8000";

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
