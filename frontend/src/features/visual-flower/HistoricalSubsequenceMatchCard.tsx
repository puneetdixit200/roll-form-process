import type { HistoricalSubsequenceMatch } from "./types";
import { HistoricalMatchRollers } from "./HistoricalMatchRollers";

export function HistoricalSubsequenceMatchCard({ match, activeGeneratedPassId, onOpenSource }: { match: HistoricalSubsequenceMatch; activeGeneratedPassId?: string; onOpenSource?: (flowerId: string, passId: string) => void }) {
  if (match.status !== "SUPPORTED") return <section className="historical-subsequence-card"><strong>Historical subsequence support: insufficient</strong><p>The generated sequence abstained because no contiguous historical interval met the support threshold.</p></section>;
  const firstPass = match.mapping?.[0]?.source_pass_id;
  return <section className="historical-subsequence-card" aria-label="Historical subsequence support">
    <strong>Historical subsequence support</strong>
    <p>{match.source_flower_id} · source passes {match.source_start_order}–{match.source_end_order} mapped to generated stages {match.generated_start_order}–{match.generated_end_order}</p>
    <p>Matched {match.matched_length} passes · alignment {(match.alignment_score! * 100).toFixed(1)}% · mean similarity {(match.mean_pass_similarity! * 100).toFixed(1)}% · progression {(match.progression_consistency! * 100).toFixed(1)}%</p>
    {onOpenSource && match.source_flower_id && firstPass && <button type="button" onClick={() => onOpenSource(match.source_flower_id!, firstPass)}>Open and highlight source interval</button>}
    <details>
      <summary>Source rollers for the selected stage</summary>
      <p>Historical roller occurrence evidence. Station associations require engineer review. Manufacturing: NOT_APPROVED. No physical asset assignment.</p>
      {!match.mapping?.some(stage => stage.generated_pass_id === activeGeneratedPassId) && <p>The selected stage is outside this matched subsequence.</p>}
      {match.mapping?.filter(stage => stage.generated_pass_id === activeGeneratedPassId).map(stage => <section key={`${stage.generated_pass_id}-${stage.source_pass_id}`}>
        <h4>Generated stage {stage.generated_order} → source stage {stage.source_order}</h4>
        <p>{stage.source_pass_id} · {stage.roller_link_status ?? "Roller library unavailable"}</p>
        <HistoricalMatchRollers rollers={stage.roller_occurrences} status={stage.roller_link_status} />
      </section>)}
    </details>
  </section>;
}
