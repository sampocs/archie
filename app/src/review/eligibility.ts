import type * as schema from "@/db/schema";
import type { TakeRow } from "@/takes/takes";
import { CHAT_KIND } from "@/ui/sourceLabels";

import type { CardRow } from "./types";

type SourceRow = typeof schema.sources.$inferSelect;
type TopicPrimerRow = typeof schema.topicPrimers.$inferSelect;
type TopicRow = typeof schema.topics.$inferSelect;
type ConversationRow = typeof schema.conversations.$inferSelect;

export type ReviewData = {
  cards: CardRow[];
  sourcesById: Map<string, SourceRow>;
  topicPrimersById: Map<string, TopicPrimerRow>;
  topicsById: Map<string, TopicRow>;
  takesById: Map<string, TakeRow>;
  conversationsById: Map<string, ConversationRow>;
};

// Where a card came from. An origin this phone doesn't know yet (a newer server's) is never reviewable here.
export type CardOrigin =
  | { kind: "source"; sourceId: string }
  | { kind: "topicPrimer"; topicPrimerId: string }
  | { kind: "brief"; briefId: string }
  | { kind: "take"; takeId: string }
  | { kind: "conversation"; conversationId: string }
  | { kind: "unknown" };

export function cardOrigin(card: CardRow): CardOrigin {
  if (card.sourceId) return { kind: "source", sourceId: card.sourceId };
  if (card.topicPrimerId) return { kind: "topicPrimer", topicPrimerId: card.topicPrimerId };
  if (card.briefId) return { kind: "brief", briefId: card.briefId };
  if (card.takeId) return { kind: "take", takeId: card.takeId };
  if (card.conversationId) return { kind: "conversation", conversationId: card.conversationId };
  return { kind: "unknown" };
}

/**
 * A card joins reviews only once you've taken in what it came from: a source's cards once it is consumed, foundation
 * cards once their primer was opened, take cards, chat cards and a chat item's cards at once. Quiz cards are answered
 * only in the quiz.
 */
export function isReviewable(card: CardRow, data: ReviewData): boolean {
  if (card.deletedAt !== null) return false;
  const origin = cardOrigin(card);
  switch (origin.kind) {
    case "source": {
      const source = data.sourcesById.get(origin.sourceId);
      if (!source || source.deletedAt !== null) return false;
      // The owner kept a chat item's cards from a chat they just had, and the item never leaves the inbox.
      if (source.kind === CHAT_KIND) return true;
      return card.kind === "foundation" ? source.primerOpenedAt !== null : source.state === "consumed";
    }
    case "topicPrimer": {
      const primer = data.topicPrimersById.get(origin.topicPrimerId);
      if (!primer || primer.openedAt === null) return false;
      const topic = data.topicsById.get(primer.topicId);
      return topic !== undefined && topic.removedAt === null && topic.mergedIntoId === null;
    }
    // You wrote what a take card came from, so it is reviewable as soon as it exists, while its take lives.
    case "take": {
      const take = data.takesById.get(origin.takeId);
      return take !== undefined && take.deletedAt === null;
    }
    // The owner made a chat card from an answer they just read, so it is reviewable at once.
    case "conversation":
      return true;
    case "brief":
    case "unknown":
      return false;
  }
}

/** A quiz card that can still be answered: not answered yet and not expired. */
export function isOpenQuiz(card: CardRow, now: Date): boolean {
  return (
    card.kind === "quiz" &&
    card.deletedAt === null &&
    card.lastReviewAt === null &&
    card.expiresAt !== null &&
    Date.parse(card.expiresAt) > now.getTime()
  );
}

/** The topic a card belongs to, through its source or topic primer. */
export function cardTopicId(card: CardRow, data: ReviewData): string | null {
  const origin = cardOrigin(card);
  if (origin.kind === "source") return data.sourcesById.get(origin.sourceId)?.topicId ?? null;
  if (origin.kind === "topicPrimer") return data.topicPrimersById.get(origin.topicPrimerId)?.topicId ?? null;
  return null;
}

/** The domain a card's kicker is coloured by: its source's, or its topic primer's topic's. */
export function cardDomain(card: CardRow, data: ReviewData): string | null {
  const origin = cardOrigin(card);
  if (origin.kind === "source") return data.sourcesById.get(origin.sourceId)?.domain ?? null;
  if (origin.kind !== "topicPrimer") return null;
  const primer = data.topicPrimersById.get(origin.topicPrimerId);
  return primer ? (data.topicsById.get(primer.topicId)?.domain ?? null) : null;
}

/** Indexes the synced rows the review logic looks cards' origins up in. */
export function makeReviewData(rows: {
  cards: CardRow[];
  sources: SourceRow[];
  topicPrimers: TopicPrimerRow[];
  topics: TopicRow[];
  takes?: TakeRow[];
  conversations?: ConversationRow[];
}): ReviewData {
  return {
    cards: rows.cards,
    sourcesById: new Map(rows.sources.map((source) => [source.id, source])),
    topicPrimersById: new Map(rows.topicPrimers.map((primer) => [primer.id, primer])),
    topicsById: new Map(rows.topics.map((topic) => [topic.id, topic])),
    takesById: new Map((rows.takes ?? []).map((take) => [take.id, take])),
    conversationsById: new Map((rows.conversations ?? []).map((conversation) => [conversation.id, conversation])),
  };
}
