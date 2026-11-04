/** Reads a summary artifact's stored JSON into the parts the source page shows. */

export type TimedItem = { timestamp: string | null };

export type SummaryContent = {
  gist: string;
  key_ideas: (TimedItem & { idea: string })[];
  numbers: (TimedItem & { fact: string })[];
};

// The worker stores the whole analysis (summary plus domain, tags, cards…); the readable part sits under `summary`.
type StoredAnalysis = { summary: SummaryContent };

export function parseSummary(content: string): SummaryContent {
  return (JSON.parse(content) as StoredAnalysis).summary;
}
