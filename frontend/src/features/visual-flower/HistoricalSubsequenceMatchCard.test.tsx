import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { expect, test } from "vitest";
import { HistoricalSubsequenceMatchCard } from "./HistoricalSubsequenceMatchCard";

test("shows source-stage roller PNG, partial status and the scoped DXF link", () => {
  const { rerender } = render(<HistoricalSubsequenceMatchCard activeGeneratedPassId="G1" match={{
    status: "SUPPORTED", source_flower_id: "F1", alignment_score: 0.8,
    mean_pass_similarity: 0.8, progression_consistency: 1,
    mapping: [{ generated_pass_id: "G1", generated_order: 4, source_pass_id: "P1", source_order: 2,
      overall_score: 0.8, mirror_used: false, rotation_used: false, components: {},
      roller_link_status: "HISTORICAL_OCCURRENCE_EVIDENCE",
      roller_occurrences: [{ roller_id: "scoped-id", occurrence_id: "R2", source_station_id: "S2",
        candidate_role: "UPPER", geometry_completeness: "PARTIAL_GEOMETRY", role_status: "CANDIDATE" }],
    }],
  }} />);
  expect(screen.getByText("Generated stage 4 → source stage 2")).toBeInTheDocument();
  expect(screen.getByAltText("UPPER roller R2")).toHaveAttribute("src", "/api/visual-flower/historical/rollers/scoped-id/png");
  expect(screen.getByText(/R2 · UPPER · PARTIAL_GEOMETRY/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download roller DXF" })).toHaveAttribute("href", "/api/visual-flower/historical/rollers/scoped-id/dxf");
  rerender(<HistoricalSubsequenceMatchCard activeGeneratedPassId="G2" match={{
    status: "SUPPORTED", mapping: [{ generated_pass_id: "G1", generated_order: 4,
      source_pass_id: "P1", source_order: 2, overall_score: 0.8, mirror_used: false,
      rotation_used: false, components: {}, roller_occurrences: [{ roller_id: "scoped-id",
        occurrence_id: "R2", source_station_id: "S2", candidate_role: "UPPER",
        geometry_completeness: "PARTIAL_GEOMETRY", role_status: "CANDIDATE" }],
    }],
  }} />);
  expect(screen.queryByAltText("UPPER roller R2")).not.toBeInTheDocument();
  expect(screen.getByText("The selected stage is outside this matched subsequence.")).toBeInTheDocument();
});
