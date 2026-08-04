import type { VisualProfile, VisualRun } from "./types";

const API_ROOT = import.meta.env.VITE_API_ROOT ?? "http://127.0.0.1:8000";
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, init);
  if (!response.ok) throw new Error(await response.text());
  return response.json() as Promise<T>;
}
export const createVisualTarget = (profile: VisualProfile) => request<{ target_id: string }>("/api/visual-flower/targets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: profile.name, profile }) });
export const generateVisualFlower = (targetId: string, preferences: Record<string, unknown>) => request<VisualRun>(`/api/visual-flower/targets/${encodeURIComponent(targetId)}/generate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(preferences) });
export const getVisualDatasetStatus = () => request<{ available: boolean; flower_count: number; pass_count: number; dataset_hash: string; warning?: string }>("/api/visual-flower/dataset-status");
