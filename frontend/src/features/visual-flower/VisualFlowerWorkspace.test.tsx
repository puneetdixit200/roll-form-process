import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { beforeEach, expect, test, vi } from "vitest";
import VisualFlowerWorkspace from "./VisualFlowerWorkspace";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("dataset-status")) return new Response(JSON.stringify({ available: true, flower_count: 2, pass_count: 31, dataset_hash: "synthetic" }), { status: 200 });
    if (url.endsWith("/targets") && init?.method === "POST") return new Response(JSON.stringify({ target_id: "target-1" }), { status: 200 });
    if (url.includes("/generate")) return new Response(JSON.stringify({ run_id: "run-1", status: "READY", candidates: [{ candidate_id: "candidate-1", candidate_style: "UNIFORM_PROGRESSION", station_count: 16, status: "VISUAL_OPEN_PROGRESSION", visual_confidence: { score: 72, band: "MODERATE_VISUAL_SUPPORT", mean_pass_confidence: 72, minimum_pass_confidence: 60, progression_smoothness: 90, non_calibrated: true }, passes: [{ pass_id: "p-1", order: 1, progress: 0, profile: { points: [[0, 0], [1, 0]], topology: "OPEN_PATH" }, historical_match: { best_match: { source_flower_id: "PRIVATE-FLOWER-001", source_pass_id: "p-1", overall_score: .8, evidence_coverage: 1 }, top_matches: [] }, visual_confidence: { score: 60, band: "WEAK_VISUAL_SUPPORT" }, warnings: [] }], warnings: [] }], warnings: [] }), { status: 200 });
    return new Response(JSON.stringify({}), { status: 200 });
  }));
});

test("loads example and exposes interactive generation controls", async () => {
  render(<VisualFlowerWorkspace />);
  expect(await screen.findByText("Historical evidence: 2 flowers, 31 passes.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Load Example" }));
  expect(screen.getByRole("button", { name: "Generate Flower Sequence" })).toBeEnabled();
});
