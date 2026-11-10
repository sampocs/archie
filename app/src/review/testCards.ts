// Row factories for review logic tests: our own rows, filled with neutral defaults. Sources, topics and topic primers
// come from the Library's factories (their rows carry a few joined fields the review code ignores).
import { sourceRow, topicPrimerRow, topicRow } from "@/library/testRows";
import type { ConversationRow } from "@/ask/types";
import type { TakeRow, TakeVersionRow } from "@/takes/takes";

import { makeReviewData, type ReviewData } from "./eligibility";
import type { CardRow, ReviewRow } from "./types";

export { sourceRow, topicPrimerRow, topicRow };

// Thursday Nov 5 2026, noon in the test zone (America/New_York).
export const NOW = new Date(2026, 10, 5, 12, 0);

/** A date `days` whole days after NOW at the given local time, as an ISO string. */
export function dayAt(days: number, hour = 12, minute = 0): string {
  return new Date(2026, 10, 5 + days, hour, minute).toISOString();
}

export const cardRow = (overrides: Partial<CardRow>): CardRow => ({
  id: "c1",
  sourceId: "s1",
  topicPrimerId: null,
  briefId: null,
  takeId: null,
  takeVersionId: null,
  kind: "concept",
  question: "Q?",
  answer: "A.",
  createdAt: "2026-11-01T00:00:00Z",
  deletedAt: null,
  fsrsState: "new",
  stability: null,
  difficulty: null,
  dueAt: null,
  lastReviewAt: null,
  reps: 0,
  lapses: 0,
  expiresAt: null,
  conversationId: null,
  messageId: null,
  version: 1,
  ...overrides,
});

/** A card already in review, due at `dueAt`. */
export const reviewCard = (overrides: Partial<CardRow> & { dueAt: string }): CardRow =>
  cardRow({
    fsrsState: "review",
    stability: 10,
    difficulty: 5,
    lastReviewAt: "2026-10-20T16:00:00Z",
    reps: 3,
    ...overrides,
  });

/** Review data where source s1 is consumed with its primer opened, and topic t1 has an opened primer p1. */
export function reviewData(
  cards: CardRow[],
  rows: Partial<
    Pick<
      Parameters<typeof makeReviewData>[0],
      "sources" | "topicPrimers" | "topics" | "takes" | "conversations" | "reviews"
    >
  > = {},
): ReviewData {
  return makeReviewData({
    cards,
    sources: rows.sources ?? [
      sourceRow({ id: "s1", state: "consumed", primerOpenedAt: "2026-11-02T00:00:00Z", topicId: "t1", domain: "AI" }),
    ],
    topicPrimers: rows.topicPrimers ?? [topicPrimerRow({ id: "p1", topicId: "t1", openedAt: "2026-11-03T00:00:00Z" })],
    topics: rows.topics ?? [topicRow({ id: "t1" })],
    takes: rows.takes ?? [],
    conversations: rows.conversations ?? [],
    reviews: rows.reviews ?? [],
  });
}

export const reviewRow = (overrides: Partial<ReviewRow>): ReviewRow => ({
  id: "r1",
  cardId: "c1",
  grade: "got_it",
  gradedBy: "model",
  answer: null,
  missing: null,
  wasDue: 1,
  reviewedAt: NOW.toISOString(),
  stateBefore: "{}",
  stateAfter: "{}",
  replacesReviewId: null,
  ...overrides,
});

export const takeRow = (overrides: Partial<TakeRow>): TakeRow => ({
  id: "k1",
  kind: "talking_point",
  title: "T",
  currentVersion: 1,
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  deletedAt: null,
  ...overrides,
});

export const takeVersionRow = (overrides: Partial<TakeVersionRow>): TakeVersionRow => ({
  id: "v1",
  takeId: "k1",
  version: 1,
  body: "Body.",
  rawBody: "Body.",
  cleaned: 0,
  cleanFailed: 0,
  createdAt: "2026-11-01T00:00:00Z",
  origin: "owner",
  ...overrides,
});

export const conversationRow = (overrides: Partial<ConversationRow>): ConversationRow => ({
  id: "chat1",
  title: "Q",
  aboutKind: null,
  aboutSourceId: null,
  aboutTopicPrimerId: null,
  aboutTakeId: null,
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  deletedAt: null,
  ...overrides,
});
