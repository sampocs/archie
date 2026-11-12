import { cardOrigin, type ReviewData } from "./eligibility";
import { GRADE_LABELS } from "./labels";
import { cardDueLabel } from "./summary";
import type { CardRow, ReviewGrade } from "./types";

export type CardPillKind = "due" | "reviewed" | "last" | "edited";

/** One meta pill under a card on its page; `grade` tints the "Last:" pill. */
export type CardPill = { kind: CardPillKind; label: string; grade: ReviewGrade | null };

/** Where a card's "From <title> ›" row goes: a source (a chat item is one), a take, or a topic primer's topic. */
export type CardSourceLink =
  | { title: string; pathname: "/source/[id]"; id: string }
  | { title: string; pathname: "/take/[id]"; id: string }
  | { title: string; pathname: "/topic/[id]"; id: string };

/**
 * The pills under a card on its page: its due label, "Reviewed N×" and "Last: <grade>" once it has been reviewed (a
 * review that "I actually knew it" replaced doesn't count), and "Edited" when it has changed since it was made.
 */
export function cardPills(card: CardRow, data: ReviewData, now: Date): CardPill[] {
  const replaced = new Set(data.reviews.map((review) => review.replacesReviewId).filter((id) => id !== null));
  const reviews = data.reviews.filter((review) => review.cardId === card.id && !replaced.has(review.id));
  const latest = reviews.reduce<(typeof reviews)[number] | null>(
    (best, review) => (best === null || Date.parse(review.reviewedAt) > Date.parse(best.reviewedAt) ? review : best),
    null,
  );
  const grade = latest ? (latest.grade as ReviewGrade) : null;

  return [
    { kind: "due", label: cardDueLabel(card, data, now), grade: null },
    ...(reviews.length > 0 ? [{ kind: "reviewed" as const, label: `Reviewed ${reviews.length}×`, grade: null }] : []),
    ...(grade && GRADE_LABELS[grade] ? [{ kind: "last" as const, label: `Last: ${GRADE_LABELS[grade]}`, grade }] : []),
    ...(card.version > 1 ? [{ kind: "edited" as const, label: "Edited", grade: null }] : []),
  ];
}

/** The item a card came from, when the phone can open it; null for a chat card, a quiz card or a gone item. */
export function cardSourceLink(card: CardRow, data: ReviewData): CardSourceLink | null {
  const origin = cardOrigin(card);
  switch (origin.kind) {
    case "source": {
      const source = data.sourcesById.get(origin.sourceId);
      return source ? { title: source.title ?? source.url, pathname: "/source/[id]", id: source.id } : null;
    }
    case "take": {
      const take = data.takesById.get(origin.takeId);
      return take ? { title: take.title, pathname: "/take/[id]", id: take.id } : null;
    }
    case "topicPrimer": {
      const primer = data.topicPrimersById.get(origin.topicPrimerId);
      const topic = primer ? data.topicsById.get(primer.topicId) : undefined;
      return topic && topic.removedAt === null ? { title: topic.name, pathname: "/topic/[id]", id: topic.id } : null;
    }
    case "conversation":
    case "brief":
    case "unknown":
      return null;
  }
}
