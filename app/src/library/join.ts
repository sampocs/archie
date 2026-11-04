import * as schema from "@/db/schema";
import { parseSummary, type SummaryContent } from "@/ui/summaryContent";

export type SourceRow = typeof schema.sources.$inferSelect;
export type TopicRow = typeof schema.topics.$inferSelect;
export type TopicPrimerRow = typeof schema.topicPrimers.$inferSelect;
type ArtifactRow = typeof schema.artifacts.$inferSelect;

export type LibrarySource = SourceRow & {
  topic: TopicRow | null;
  summary: SummaryContent | null;
  // When the current primer artifact was written; null when the source has no primer.
  primerCreatedAt: string | null;
};

export type LibraryData = { sources: LibrarySource[]; topics: TopicRow[]; topicPrimers: TopicPrimerRow[] };

export function isLiveTopic(topic: TopicRow): boolean {
  return !topic.removedAt && !topic.mergedIntoId;
}

/** Attaches each source's topic, current summary and primer time; `artifacts` must be current ones only. */
export function joinLibrary(input: {
  sources: SourceRow[];
  artifacts: ArtifactRow[];
  topics: TopicRow[];
  topicPrimers: TopicPrimerRow[];
}): LibraryData {
  const topicsById = new Map(input.topics.map((topic) => [topic.id, topic]));
  const summaries = new Map<string, SummaryContent>();
  const primerTimes = new Map<string, string>();
  for (const artifact of input.artifacts) {
    if (artifact.kind === "summary") summaries.set(artifact.sourceId, parseSummary(artifact.content));
    if (artifact.kind === "primer") primerTimes.set(artifact.sourceId, artifact.createdAt);
  }

  return {
    sources: input.sources.map((source) => ({
      ...source,
      topic: source.topicId ? (topicsById.get(source.topicId) ?? null) : null,
      summary: summaries.get(source.id) ?? null,
      primerCreatedAt: primerTimes.get(source.id) ?? null,
    })),
    topics: input.topics,
    topicPrimers: input.topicPrimers,
  };
}
