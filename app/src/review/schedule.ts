import { createEmptyCard, fsrs, generatorParameters, Rating, State, type Card as FsrsCard } from "ts-fsrs";

import type { FsrsFields, FsrsStateName, ReviewGrade } from "./types";

// Long-term only: a session shows each card once, so same-day learning steps would never be honored, and there is no
// column for them. No fuzz, so a grade always schedules the same way (and the tests can say exactly how).
const scheduler = fsrs(generatorParameters({ enable_short_term: false, enable_fuzz: false }));

const RATING_BY_GRADE = { got_it: Rating.Good, partly: Rating.Hard, missed: Rating.Again } as const;
const STATE_BY_NAME: Record<FsrsStateName, State> = {
  new: State.New,
  learning: State.Learning,
  review: State.Review,
  relearning: State.Relearning,
};
const NAME_BY_STATE: Record<State, FsrsStateName> = {
  [State.New]: "new",
  [State.Learning]: "learning",
  [State.Review]: "review",
  [State.Relearning]: "relearning",
};
const DAY_MS = 86_400_000;

/**
 * The card's state after a grade. Extra practice (a card that wasn't due) can only bring a card sooner: got_it leaves
 * it as it was, and partly/missed never move it later than it already was. Quiz cards are never scheduled; the
 * review only marks them answered.
 */
export function applyGrade(
  card: FsrsFields & { kind: string },
  grade: ReviewGrade,
  now: Date,
  wasDue: boolean,
): FsrsFields {
  const before = pickFields(card);
  if (card.kind === "quiz") return { ...before, lastReviewAt: now.toISOString() };
  if (!wasDue && grade === "got_it") return before;

  const after = fromFsrsCard(scheduler.next(toFsrsCard(before, now), now, RATING_BY_GRADE[grade]).card);
  if (wasDue || before.dueAt === null || after.dueAt === null) return after;
  return Date.parse(after.dueAt) > Date.parse(before.dueAt) ? { ...after, dueAt: before.dueAt } : after;
}

/** "I actually knew it": redo the replaced review as a got_it from the state it started from. */
export function knewItState(
  kind: string,
  replaced: { stateBefore: FsrsFields; reviewedAt: string; wasDue: boolean },
): FsrsFields {
  return applyGrade({ ...replaced.stateBefore, kind }, "got_it", new Date(replaced.reviewedAt), replaced.wasDue);
}

function pickFields(card: FsrsFields): FsrsFields {
  const { fsrsState, stability, difficulty, dueAt, lastReviewAt, reps, lapses } = card;
  return { fsrsState, stability, difficulty, dueAt, lastReviewAt, reps, lapses };
}

function toFsrsCard(fields: FsrsFields, now: Date): FsrsCard {
  if (fields.fsrsState === "new" || fields.stability === null || fields.difficulty === null) {
    return { ...createEmptyCard(now), reps: fields.reps, lapses: fields.lapses };
  }

  const due = new Date(fields.dueAt ?? now.toISOString());
  const lastReview = fields.lastReviewAt ? new Date(fields.lastReviewAt) : undefined;
  return {
    due,
    stability: fields.stability,
    difficulty: fields.difficulty,
    elapsed_days: lastReview ? Math.max(0, Math.floor((now.getTime() - lastReview.getTime()) / DAY_MS)) : 0,
    scheduled_days: lastReview ? Math.max(0, Math.round((due.getTime() - lastReview.getTime()) / DAY_MS)) : 0,
    learning_steps: 0,
    reps: fields.reps,
    lapses: fields.lapses,
    state: STATE_BY_NAME[fields.fsrsState],
    last_review: lastReview,
  };
}

function fromFsrsCard(card: FsrsCard): FsrsFields {
  return {
    fsrsState: NAME_BY_STATE[card.state],
    stability: card.stability,
    difficulty: card.difficulty,
    dueAt: card.due.toISOString(),
    lastReviewAt: card.last_review ? card.last_review.toISOString() : null,
    reps: card.reps,
    lapses: card.lapses,
  };
}
