import * as schema from "@/db/schema";
import { parseSummary, type SummaryContent } from "@/ui/summaryContent";

import { primerMarkdown, wordCount } from "./primer";

export type SourceRow = typeof schema.sources.$inferSelect;
export type TopicRow = typeof schema.topics.$inferSelect;
export type TopicPrimerRow = typeof schema.topicPrimers.$inferSelect;
type ArtifactRow = typeof schema.artifacts.$inferSelect;

export type LibrarySource = SourceRow & {
  topic: TopicRow | null;
  summary: SummaryContent | null;
  // When the current primer artifact was written; null when the source has no primer.
  primerCreatedAt: string | null;
  // The current primer's length in words, for its reading time; null when the source has no primer.
  primerWords: number | null;
  // How many live cards the source has; 0 when none.
  cardCount: number;
};

export type LibraryData = {
  sources: LibrarySource[];
  // Signup-confirmation emails (sources with a confirmUrl), newest first; never in `sources`.
  confirmations: LibrarySource[];
  // Newsletters from a sender the owner hasn't allowed yet (senderPending), newest first; never in `sources`.
  pendingSenders: LibrarySource[];
  topics: TopicRow[];
  topicPrimers: TopicPrimerRow[];
};

export function isLiveTopic(topic: TopicRow): boolean {
  return !topic.removedAt && !topic.mergedIntoId;
}

/**
 * Attaches each source's topic, current summary and primer time and length, and its live card count; `artifacts` must be current ones only.
 * Sources with a confirmUrl are split out into `confirmations`, and those awaiting a sender decision into
 * `pendingSenders`, so every reader of `sources` skips them. A confirmation is never pending.
 */
export function joinLibrary(input: {
  sources: SourceRow[];
  artifacts: ArtifactRow[];
  topics: TopicRow[];
  topicPrimers: TopicPrimerRow[];
  // Live cards per source id; a source without an entry has none.
  cardCounts: Map<string, number>;
}): LibraryData {
  const topicsById = new Map(input.topics.map((topic) => [topic.id, topic]));
  const summaries = new Map<string, SummaryContent>();
  const primers = new Map<string, { createdAt: string; words: number }>();
  for (const artifact of input.artifacts) {
    if (artifact.kind === "summary") summaries.set(artifact.sourceId, parseSummary(artifact.content));
    if (artifact.kind === "primer") {
      const words = wordCount(primerMarkdown(artifact.content));
      primers.set(artifact.sourceId, { createdAt: artifact.createdAt, words });
    }
  }

  const joined = input.sources.map((source) => ({
    ...source,
    topic: source.topicId ? (topicsById.get(source.topicId) ?? null) : null,
    summary: summaries.get(source.id) ?? null,
    primerCreatedAt: primers.get(source.id)?.createdAt ?? null,
    primerWords: primers.get(source.id)?.words ?? null,
    cardCount: input.cardCounts.get(source.id) ?? 0,
  }));
  const newestFirst = (first: LibrarySource, second: LibrarySource) => second.createdAt.localeCompare(first.createdAt);
  const confirmations = joined.filter((source) => source.confirmUrl !== null).sort(newestFirst);
  const pendingSenders = joined
    .filter((source) => source.confirmUrl === null && source.senderPending)
    .sort(newestFirst);

  return {
    sources: joined.filter((source) => source.confirmUrl === null && !source.senderPending),
    confirmations,
    pendingSenders,
    topics: input.topics,
    topicPrimers: input.topicPrimers,
  };
}
