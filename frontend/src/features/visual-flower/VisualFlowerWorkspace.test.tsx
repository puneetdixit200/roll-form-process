import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { beforeEach, expect, test, vi } from "vitest";
import VisualFlowerWorkspace from "./VisualFlowerWorkspace";
import { ProfileSketcher } from "./ProfileSketcher";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.includes("dataset-status")) return new Response(JSON.stringify({ available: true, flower_count: 2, pass_count: 31, dataset_hash: "synthetic" }), { status: 200 });
    if (url.endsWith("/targets") && init?.method === "POST") return new Response(JSON.stringify({ target_id: "target-1" }), { status: 200 });
    if (url.includes("/generate")) return new Response(JSON.stringify({ run_id: "run-1", status: "READY", candidates: [{ candidate_id: "candidate-1", candidate_style: "UNIFORM_PROGRESSION", station_count: 16, status: "VISUAL_OPEN_PROGRESSION", visual_confidence: { score: 72, band: "MODERATE_VISUAL_SUPPORT", mean_pass_confidence: 72, minimum_pass_confidence: 60, progression_smoothness: 90, non_calibrated: true }, geometry_constraints: { enabled: true, constraint_version: "constant_centerline_length_v1", target_length: 4.2381, maximum_relative_error: 0, relative_tolerance: 1e-6, satisfied: true, open_path_local_segment_lengths_preserved: true }, passes: [{ pass_id: "p-1", order: 1, progress: 0, profile: { points: [[0, 0], [1, 0]], topology: "OPEN_PATH" }, generation: { strip_length_constraint: { enabled: true, constraint_version: "constant_centerline_length_v1", reference: "FINAL_TARGET_CENTERLINE", coordinate_space: "CANONICAL_VISUAL_UNITS", method: "OPEN_SEGMENT_LENGTH_TANGENT_PROJECTION", target_length: 4.2381, before_length: 4.1, actual_length: 4.2381, relative_error: 0, relative_tolerance: 1e-6, satisfied: true, local_segment_lengths_preserved: true, projection_rms: 0.2, visual_only: true } }, historical_match: { best_match: { source_flower_id: "PRIVATE-FLOWER-001", source_pass_id: "p-1", overall_score: .8, evidence_coverage: 1 }, top_matches: [] }, visual_confidence: { score: 60, band: "WEAK_VISUAL_SUPPORT" }, warnings: [] }], warnings: [] }], warnings: [] }), { status: 200 });
    return new Response(JSON.stringify({}), { status: 200 });
  }));
});

test("loads example and exposes interactive generation controls", async () => {
  render(<VisualFlowerWorkspace />);
  expect(await screen.findByText("Historical evidence: 2 flowers, 31 passes.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Load Example" }));
  fireEvent.click(screen.getByRole("button", { name: "Validate Profile" }));
  expect(screen.getByRole("button", { name: "Generate Flower Sequence" })).toBeEnabled();
});

test("renders stored arcs as SVG arc paths", () => {
  render(<ProfileSketcher profile={{ schema_version: 1, profile_id: "arc", name: "Arc", topology: "OPEN_PATH", closed: false, computational_seam_vertex_id: null, vertices: [{ vertex_id: "a", x: 0, y: 0 }, { vertex_id: "b", x: 1, y: 1 }], segments: [{ segment_id: "arc-1", type: "ARC", start_vertex_id: "a", end_vertex_id: "b", center: { x: 0, y: 1 }, radius: 1, clockwise: false }], metadata: { source: "PUBLIC_SYNTHETIC_TEST", visual_only: true } }} onChange={() => undefined} />);
  expect(screen.getByTestId("visual-arc-path")).toHaveAttribute("d", expect.stringContaining(" A "));
});

test("shows locked constant strip-length evidence after generation", async () => {
  render(<VisualFlowerWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "Generate Flower Sequence" }));
  expect(await screen.findByText("Strip length: LOCKED")).toBeInTheDocument();
  expect(screen.getAllByText("Target centerline: 4.2381 visual units")).toHaveLength(2);
  expect(screen.getByText("Current station centerline constraint")).toBeInTheDocument();
  expect(screen.getByText("Material-coordinate segment lengths: PRESERVED")).toBeInTheDocument();
});
