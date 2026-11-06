import type * as schema from "@/db/schema";

export type ReviewGrade = "got_it" | "partly" | "missed";
export type GradedBy = "model" | "self";
export type FsrsStateName = "new" | "learning" | "review" | "relearning";
export type CardRow = typeof schema.cards.$inferSelect;
export type ReviewRow = typeof schema.reviews.$inferSelect;

// The card columns the scheduler owns; also the shape stored in reviews.stateBefore/stateAfter.
export type FsrsFields = {
  fsrsState: FsrsStateName;
  stability: number | null;
  difficulty: number | null;
  dueAt: string | null;
  lastReviewAt: string | null;
  reps: number;
  lapses: number;
};

export function fsrsFieldsOf(card: CardRow): FsrsFields {
  return {
    fsrsState: card.fsrsState as FsrsStateName,
    stability: card.stability,
    difficulty: card.difficulty,
    dueAt: card.dueAt,
    lastReviewAt: card.lastReviewAt,
    reps: card.reps,
    lapses: card.lapses,
  };
}

/** The FsrsState object review_card sends (snake_case, as the server stores it). */
export function wireState(fields: FsrsFields): Record<string, unknown> {
  return {
    fsrs_state: fields.fsrsState,
    stability: fields.stability,
    difficulty: fields.difficulty,
    due_at: fields.dueAt,
    last_review_at: fields.lastReviewAt,
    reps: fields.reps,
    lapses: fields.lapses,
  };
}
