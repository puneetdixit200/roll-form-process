import { historicalRollerAssetUrl } from "./api";
import type { HistoricalRollerOccurrence } from "./types";

export function HistoricalMatchRollers({ rollers, status }: {
  rollers?: HistoricalRollerOccurrence[];
  status?: string;
}) {
  return <section aria-label="Rollers for this exact historical match">
    <strong>Rollers for this matched source stage only</strong>
    {!rollers?.length && <p>{status === "NO_ROLLER_DETECTED" ? "No roller was detected at this source stage." : status ?? "Regenerate to load rollers for this match."}</p>}
    {rollers?.map(roller => <figure key={roller.roller_id}>
      <img loading="lazy" src={historicalRollerAssetUrl(roller.roller_id, "png")} alt={`${roller.candidate_role} roller ${roller.occurrence_id}`} style={{ width: 240, maxWidth: "100%" }} />
      <figcaption>{roller.occurrence_id} · {roller.candidate_role} · {roller.geometry_completeness}</figcaption>
      <a href={historicalRollerAssetUrl(roller.roller_id, "dxf")} download={`${roller.occurrence_id}.dxf`}>Download roller DXF</a>
    </figure>)}
    <p>Historical evidence; association requires review. Manufacturing: NOT_APPROVED.</p>
  </section>;
}
