import type { HistoricalSubsequenceMatch } from "./types";
import { historicalRollerAssetUrl } from "./api";

export function HistoricalSubsequenceMatchCard({ match, onOpenSource }: { match: HistoricalSubsequenceMatch; onOpenSource?: (flowerId: string, passId: string) => void }) {
  if (match.status !== "SUPPORTED") return <section className="historical-subsequence-card"><strong>Historical subsequence support: insufficient</strong><p>The generated sequence abstained because no contiguous historical interval met the support threshold.</p></section>;
  const firstPass = match.mapping?.[0]?.source_pass_id;
  return <section className="historical-subsequence-card" aria-label="Historical subsequence support">
    <strong>Historical subsequence support</strong>
    <p>{match.source_flower_id} · source passes {match.source_start_order}–{match.source_end_order} mapped to generated stages {match.generated_start_order}–{match.generated_end_order}</p>
    <p>Matched {match.matched_length} passes · alignment {(match.alignment_score! * 100).toFixed(1)}% · mean similarity {(match.mean_pass_similarity! * 100).toFixed(1)}% · progression {(match.progression_consistency! * 100).toFixed(1)}%</p>
    {onOpenSource && match.source_flower_id && firstPass && <button type="button" onClick={() => onOpenSource(match.source_flower_id!, firstPass)}>Open and highlight source interval</button>}
    <details>
      <summary>Source rollers for each matched stage</summary>
      <p>Historical roller occurrence evidence. Station associations require engineer review. Manufacturing: NOT_APPROVED. No physical asset assignment.</p>
      {match.mapping?.map(stage => <section key={`${stage.generated_pass_id}-${stage.source_pass_id}`}>
        <h4>Generated stage {stage.generated_order} → source stage {stage.source_order}</h4>
        <p>{stage.source_pass_id} · {stage.roller_link_status ?? "Roller library unavailable"}</p>
        {stage.roller_occurrences?.map(roller => <figure key={roller.roller_id}>
          <img loading="lazy" src={historicalRollerAssetUrl(roller.roller_id, "png")} alt={`${roller.candidate_role} roller ${roller.occurrence_id}`} style={{ width: 240, maxWidth: "100%" }} />
          <figcaption>{roller.occurrence_id} · {roller.candidate_role} · {roller.geometry_completeness}</figcaption>
          <a href={historicalRollerAssetUrl(roller.roller_id, "dxf")} download={`${roller.occurrence_id}.dxf`}>Download roller DXF</a>
        </figure>)}
      </section>)}
    </details>
  </section>;
}
