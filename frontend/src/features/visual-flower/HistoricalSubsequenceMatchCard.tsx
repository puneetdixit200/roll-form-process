import type { HistoricalSubsequenceMatch } from "./types";

export function HistoricalSubsequenceMatchCard({ match, onOpenSource }: { match: HistoricalSubsequenceMatch; onOpenSource?: (flowerId: string, passId: string) => void }) {
  if (match.status !== "SUPPORTED") return <section className="historical-subsequence-card"><strong>Historical subsequence support: insufficient</strong><p>The generated sequence abstained because no contiguous historical interval met the support threshold.</p></section>;
  const firstPass = match.mapping?.[0]?.source_pass_id;
  return <section className="historical-subsequence-card" aria-label="Historical subsequence support">
    <strong>Historical subsequence support</strong>
    <p>{match.source_flower_id} · source passes {match.source_start_order}–{match.source_end_order} mapped to generated stages {match.generated_start_order}–{match.generated_end_order}</p>
    <p>Matched {match.matched_length} passes · alignment {(match.alignment_score! * 100).toFixed(1)}% · mean similarity {(match.mean_pass_similarity! * 100).toFixed(1)}% · progression {(match.progression_consistency! * 100).toFixed(1)}%</p>
    {onOpenSource && match.source_flower_id && firstPass && <button type="button" onClick={() => onOpenSource(match.source_flower_id!, firstPass)}>Open and highlight source interval</button>}
  </section>;
}
