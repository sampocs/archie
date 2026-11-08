/** Reads a summary artifact's stored JSON into the parts the source page shows. */

export type TimedItem = { timestamp: string | null };

export type SummaryContent = {
  gist: string;
  key_ideas: (TimedItem & { idea: string })[];
  numbers: (TimedItem & { fact: string })[];
  // The pages a note's write-up drew on; stored beside `summary`, absent for other kinds.
  sources?: { url: string; title: string }[];
};

// The worker stores the whole analysis (summary plus domain, tags, cards…); the readable part sits under `summary`.
type StoredAnalysis = { summary: SummaryContent; sources?: { url: string; title: string }[] };

export function parseSummary(content: string): SummaryContent {
  const stored = JSON.parse(content) as StoredAnalysis;
  return stored.sources ? { ...stored.summary, sources: stored.sources } : stored.summary;
}
