// The Review tab's browsing, kept pure so it can be tested: its Topics, Items and Missed lists, search, the streak,
// Shuffle's pick, and the card list a topic or item opens. Everything here works on live, reviewable cards only.
import type * as schema from "@/db/schema";
import type { TakeRow } from "@/takes/takes";

import { MISSED_WINDOW_DAYS } from "./constants";
import { isDue } from "./due";
import { cardOrigin, cardTopicId, isReviewable, type ReviewData, type ReviewLogRow } from "./eligibility";
import { KIND_LABELS } from "./labels";
import type { CardRow, ReviewGrade, ReviewRow } from "./types";

type SourceRow = typeof schema.sources.$inferSelect;
type TopicRow = typeof schema.topics.$inferSelect;

const DAY_MS = 86_400_000;
const MISSED: ReviewGrade = "missed";
const PARTLY: ReviewGrade = "partly";
// A partly answer counts as half a miss when ranking the Missed list.
const PARTLY_WEIGHT = 0.5;

export type BrowseMode = "topics" | "items" | "missed";
export const BROWSE_MODES: readonly BrowseMode[] = ["topics", "items", "missed"];

/** A stored browse mode; anything unknown (or nothing stored yet) is Topics. */
export function asBrowseMode(value: string | null | undefined): BrowseMode {
  return BROWSE_MODES.find((mode) => mode === value) ?? "topics";
}

/** The cards the Review tab counts, searches and lists: live and reviewable now. */
export function browsableCards(data: ReviewData): CardRow[] {
  return data.cards.filter((card) => isReviewable(card, data));
}

export type TopicBrowseRow = { topic: TopicRow; count: number; due: number };

/** Each live topic with reviewable cards, how many it has and how many are due: busiest first, then by name. */
export function browseTopics(data: ReviewData, now: Date): TopicBrowseRow[] {
  const rowsById = new Map<string, TopicBrowseRow>();
  for (const card of browsableCards(data)) {
    const topicId = cardTopicId(card, data);
    const topic = topicId === null ? undefined : data.topicsById.get(topicId);
    if (!topic || topic.removedAt !== null || topic.mergedIntoId !== null) continue;

    const row = rowsById.get(topic.id) ?? { topic, count: 0, due: 0 };
    rowsById.set(topic.id, { topic, count: row.count + 1, due: row.due + (isDue(card, now) ? 1 : 0) });
  }
  return [...rowsById.values()].sort((a, b) => b.count - a.count || a.topic.name.localeCompare(b.topic.name));
}

export type ItemBrowseRow =
  | { kind: "source"; source: SourceRow; count: number; due: number; latestAt: number }
  | { kind: "take"; take: TakeRow; count: number; due: number; latestAt: number };

/** Sources and takes with reviewable cards, the most recently reviewed or created card's item first. */
export function browseItems(data: ReviewData, now: Date): ItemBrowseRow[] {
  const rowsByKey = new Map<string, ItemBrowseRow>();
  for (const card of browsableCards(data)) {
    const origin = cardOrigin(card);
    const source = origin.kind === "source" ? data.sourcesById.get(origin.sourceId) : undefined;
    const take = origin.kind === "take" ? data.takesById.get(origin.takeId) : undefined;
    const item = source ? ({ kind: "source", source } as const) : take ? ({ kind: "take", take } as const) : null;
    if (item === null) continue;
    const key = item.kind === "source" ? `source:${item.source.id}` : `take:${item.take.id}`;

    // A card's latest moment is its last review, or its making if it was never reviewed.
    const cardAt = Math.max(Date.parse(card.createdAt), card.lastReviewAt ? Date.parse(card.lastReviewAt) : 0);
    const due = isDue(card, now) ? 1 : 0;
    const previous = rowsByKey.get(key);
    const totals = {
      count: (previous?.count ?? 0) + 1,
      due: (previous?.due ?? 0) + due,
      latestAt: Math.max(previous?.latestAt ?? 0, cardAt),
    };
    rowsByKey.set(key, { ...item, ...totals });
  }
  return [...rowsByKey.values()].sort((a, b) => b.latestAt - a.latestAt || itemTitle(a).localeCompare(itemTitle(b)));
}

/** An Items row's title: a source's (or its link when untitled), or a take's. */
export function itemTitle(row: ItemBrowseRow): string {
  return row.kind === "source" ? (row.source.title ?? row.source.url) : row.take.title;
}

export type MissedCard = { card: CardRow; missed: number; partly: number; lastReviewedAt: number };

/**
 * Cards whose latest review in the last 30 days was missed or partly, worst first: misses in that window (a partly
 * counting half), then the most recently reviewed. A review "I actually knew it" replaced doesn't count.
 */
export function missedCards(data: ReviewData, now: Date): MissedCard[] {
  const since = now.getTime() - MISSED_WINDOW_DAYS * DAY_MS;
  const replaced = new Set(data.reviews.map((review) => review.replacesReviewId).filter((id) => id !== null));
  const reviewsByCard = new Map<string, ReviewLogRow[]>();
  for (const review of data.reviews) {
    if (replaced.has(review.id) || Date.parse(review.reviewedAt) < since) continue;
    const own = reviewsByCard.get(review.cardId);
    if (own) own.push(review);
    else reviewsByCard.set(review.cardId, [review]);
  }

  const entries = browsableCards(data).flatMap((card) => {
    const reviews = reviewsByCard.get(card.id) ?? [];
    const latest = reviews.reduce<ReviewLogRow | null>(
      (best, review) => (best === null || Date.parse(review.reviewedAt) > Date.parse(best.reviewedAt) ? review : best),
      null,
    );
    if (latest === null || (latest.grade !== MISSED && latest.grade !== PARTLY)) return [];
    return [
      {
        card,
        missed: reviews.filter((review) => review.grade === MISSED).length,
        partly: reviews.filter((review) => review.grade === PARTLY).length,
        lastReviewedAt: Date.parse(latest.reviewedAt),
      },
    ];
  });
  const weight = (entry: MissedCard): number => entry.missed + entry.partly * PARTLY_WEIGHT;
  return entries.sort(
    (a, b) => weight(b) - weight(a) || b.lastReviewedAt - a.lastReviewedAt || a.card.id.localeCompare(b.card.id),
  );
}

/** A Missed row's tag: "missed", "missed 2×", or "partly" when it was only ever partly. */
export function missedTag(entry: MissedCard): string {
  if (entry.missed === 0) return "partly";
  return entry.missed === 1 ? "missed" : `missed ${entry.missed}×`;
}

/** The cards whose question or answer contains the query, ignoring case; nothing for a blank query. */
export function searchCards(cards: CardRow[], query: string): CardRow[] {
  const needle = query.trim().toLowerCase();
  if (needle === "") return [];
  return cards.filter(
    (card) => card.question.toLowerCase().includes(needle) || card.answer.toLowerCase().includes(needle),
  );
}

/** Consecutive local days with at least one review, ending today or (if nothing yet today) yesterday. */
export function reviewStreak(reviews: Pick<ReviewRow, "reviewedAt">[], now: Date): number {
  const days = new Set(reviews.map((review) => localDayKey(new Date(review.reviewedAt))));
  const dayBefore = (daysBack: number): Date => new Date(now.getFullYear(), now.getMonth(), now.getDate() - daysBack);

  // Not having reviewed yet today doesn't break a streak that ran through yesterday.
  const start = days.has(localDayKey(now)) ? 0 : 1;
  let streak = 0;
  while (days.has(localDayKey(dayBefore(start + streak)))) streak += 1;
  return streak;
}

/** Up to `count` items in random order (a partial Fisher–Yates shuffle); `random` is injectable for tests. */
export function shufflePick<T>(items: T[], count: number, random: () => number = Math.random): T[] {
  const pool = [...items];
  const picked = Math.min(count, pool.length);
  for (let index = 0; index < picked; index += 1) {
    const swap = index + Math.floor(random() * (pool.length - index));
    [pool[index], pool[swap]] = [pool[swap], pool[index]];
  }
  return pool.slice(0, picked);
}

// The card list screen's subject; its kind doubles as the session mode that practices it.
export type CardListTarget = { kind: "topic" | "source" | "take"; id: string };

/** The card list a `/review/cards` link names: `?topic=`, `?source=` or `?take=` (the first one given). */
export function cardListTargetOf(params: { topic?: string; source?: string; take?: string }): CardListTarget | null {
  if (params.topic) return { kind: "topic", id: params.topic };
  if (params.source) return { kind: "source", id: params.source };
  if (params.take) return { kind: "take", id: params.take };
  return null;
}

/** A topic's or item's name and its reviewable cards (unordered), or null when this phone doesn't have it. */
export function cardListOf(data: ReviewData, target: CardListTarget): { title: string; cards: CardRow[] } | null {
  const cards = browsableCards(data);
  switch (target.kind) {
    case "topic": {
      const topic = data.topicsById.get(target.id);
      if (!topic) return null;
      return { title: topic.name, cards: cards.filter((card) => cardTopicId(card, data) === target.id) };
    }
    case "source": {
      const source = data.sourcesById.get(target.id);
      if (!source) return null;
      return { title: source.title ?? source.url, cards: cards.filter((card) => card.sourceId === target.id) };
    }
    case "take": {
      const take = data.takesById.get(target.id);
      if (!take) return null;
      return { title: take.title, cards: cards.filter((card) => card.takeId === target.id) };
    }
  }
}

/** Where a card came from, for a row that mixes items: "From {title}", or its kind for a topic's foundation card. */
export function cardOriginLabel(card: CardRow, data: ReviewData): string {
  const origin = cardOrigin(card);
  const title =
    origin.kind === "source"
      ? (data.sourcesById.get(origin.sourceId)?.title ?? null)
      : origin.kind === "take"
        ? (data.takesById.get(origin.takeId)?.title ?? null)
        : origin.kind === "conversation"
          ? (data.conversationsById.get(origin.conversationId)?.title ?? null)
          : null;
  return title ? `From ${title}` : (KIND_LABELS[card.kind] ?? card.kind);
}

// Calendar days in the phone's zone, so a streak follows local midnights (and DST days of 23 or 25 hours).
function localDayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}
