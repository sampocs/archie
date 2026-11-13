/**
 * Today's tasks (review, note refresher, news quiz, brief): whether each is waiting, under way or done today, and the
 * "Today's done" copy. Pure, so local-day boundaries are testable.
 */

import { parseBriefContent, storiesInOrder, todayBrief, type BriefRow, type TodayBrief } from "@/brief/brief";
import type { LibrarySource } from "@/library/join";
import { DAILY_NOTES, refresherQueue, todayRefresher, type TodayRefresher } from "@/notes/refresher";
import { dailyPlan, reviewedDueToday } from "@/review/dailyCap";
import { isReviewable, type ReviewData, type ReviewLogRow } from "@/review/eligibility";
import { cardsWord } from "@/review/labels";
import { quizOffer } from "@/review/newsQuiz";
import { effectiveDue, isDue } from "@/review/due";
import { daysFrom, minutesFor, nextReview, shortWeekday } from "@/review/summary";
import { MONTHS, sameLocalDay } from "@/today/todayLabels";

export const TASK_KINDS = ["review", "notes", "quiz", "brief"] as const;
export type TaskKind = (typeof TASK_KINDS)[number];

const PENDING = "pending";
const IN_PROGRESS = "inProgress";
const DONE = "done";
const QUIZ_KIND = "quiz";
const GOT_IT = "got_it";
// Past this many days out, the next review is named by its date rather than its weekday.
const WEEKDAY_WINDOW_DAYS = 6;

// `due` is today's capped set; `waiting` the due cards the daily cap holds back.
export type ReviewTask =
  | { status: typeof PENDING; due: number; minutes: number; waiting: number }
  | { status: typeof IN_PROGRESS; due: number; minutes: number; reviewed: number; total: number }
  // `next` is "5 tomorrow" / "5 on Thu": when cards next come due; null when none wait.
  | { status: typeof DONE; reviewed: number; next: string | null; waiting: number };

export type NotesTask =
  | { status: typeof PENDING | typeof IN_PROGRESS; refresher: Extract<TodayRefresher, { kind: "pick" }> }
  | { status: typeof DONE; refreshed: number; next: LibrarySource | null };

export type QuizTask =
  | { status: typeof PENDING; count: number; until: Date }
  | { status: typeof DONE; gotIt: number; answered: number };

export type BriefTask =
  | { status: typeof PENDING; brief: NonNullable<TodayBrief> }
  | { status: typeof DONE; stories: number };

/** Each task's state today; null for a task that has nothing to show today. */
export type TodayTasks = {
  review: ReviewTask | null;
  notes: NotesTask | null;
  quiz: QuizTask | null;
  brief: BriefTask | null;
  // At least one task was done today and none is still waiting.
  dayDone: boolean;
};

export type TodayInputs = {
  reviewData: ReviewData;
  // The phone's whole review log; only today's (and, for the quiz, each card's latest) rows matter.
  reviews: ReviewLogRow[];
  sources: LibrarySource[];
  briefs: BriefRow[];
  // Cards per day; null for no cap.
  dailyLimit: number | null;
  now: Date;
};

/** Every task's state on Today. */
export function todayTasks(inputs: TodayInputs): TodayTasks {
  const tasks = {
    review: reviewTask(inputs),
    notes: notesTask(inputs.sources, inputs.now),
    quiz: quizTask(inputs),
    brief: briefTask(inputs),
  };
  const shown = TASK_KINDS.map((kind) => tasks[kind]).filter((task) => task !== null);
  const dayDone = shown.length > 0 && shown.every((task) => task.status === DONE);
  return { ...tasks, dayDone };
}

/** The tasks finished today, in Today's order. */
export function doneTaskKinds(tasks: TodayTasks): TaskKind[] {
  return TASK_KINDS.filter((kind) => tasks[kind]?.status === DONE);
}

/** The ticked chips on "Today's done": "12 cards", "2 notes", "Brief", "Quiz". */
export function dayDoneChips(tasks: TodayTasks): string[] {
  const chips: Record<TaskKind, string | null> = {
    review: tasks.review?.status === DONE ? cardsWord(tasks.review.reviewed) : null,
    notes: tasks.notes?.status === DONE ? notesWord(tasks.notes.refreshed) : null,
    quiz: tasks.quiz?.status === DONE ? "Quiz" : null,
    brief: tasks.brief?.status === DONE ? "Brief" : null,
  };
  return TASK_KINDS.map((kind) => chips[kind]).filter((chip) => chip !== null);
}

/** What tomorrow already holds: cards and notes queued, and whether a brief is expected. */
export type TomorrowCounts = { cards: number; notes: number; brief: boolean };

export function tomorrowCounts(inputs: TodayInputs, tasks: TodayTasks): TomorrowCounts {
  // Cards the cap held back today lead tomorrow's set, which the cap limits too.
  const waiting = dailyPlan(inputs.reviewData, inputs.dailyLimit, inputs.now).waiting.length;
  const cards = Math.min(waiting + dueByTomorrow(inputs.reviewData, inputs.now), inputs.dailyLimit ?? Infinity);
  const notes = Math.min(refresherQueue(inputs.sources).length, DAILY_NOTES);

  // A brief comes most days for someone who read one today; there's no way to know tomorrow's for sure.
  return { cards, notes, brief: tasks.brief?.status === DONE };
}

/** "Back tomorrow: 5 cards, 2 notes and a new brief." from what tomorrow already holds. */
export function backTomorrow(tomorrow: TomorrowCounts): string {
  const parts = [
    tomorrow.cards > 0 ? cardsWord(tomorrow.cards) : null,
    tomorrow.notes > 0 ? notesWord(tomorrow.notes) : null,
    tomorrow.brief ? "a new brief" : null,
  ].filter((part) => part !== null);
  return parts.length === 0 ? "Back tomorrow." : `Back tomorrow: ${joinNaturally(parts)}.`;
}

/** "1 note" / "2 notes". */
export function notesWord(count: number): string {
  return count === 1 ? "1 note" : `${count} notes`;
}

/** "a", "a and b", "a, b and c". */
export function joinNaturally(parts: string[]): string {
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/**
 * Today's review set is the cards reviewed today that were due plus today's capped set of due cards; with none
 * reviewed yet it is waiting, with some reviewed and some left it is under way, and with none left it is done, even
 * when the cap left cards waiting.
 */
function reviewTask({ reviewData, reviews, dailyLimit, now }: TodayInputs): ReviewTask | null {
  const plan = dailyPlan(reviewData, dailyLimit, now);
  const due = plan.today.length;
  const waiting = plan.waiting.length;
  const reviewed = reviewedDueToday(reviewData, reviews, now);
  const minutes = minutesFor(due);

  if (reviewed === 0) return due > 0 ? { status: PENDING, due, minutes, waiting } : null;
  if (due > 0) return { status: IN_PROGRESS, due, minutes, reviewed, total: reviewed + due };

  const next = nextReview(reviewData, now);
  return { status: DONE, reviewed, next: next ? `${next.count} ${nextDayWord(next.at, now)}` : null, waiting };
}

// "later today", "tomorrow", "on Thu" within a week, else "on Nov 14".
function nextDayWord(at: Date, now: Date): string {
  const days = daysFrom(now, at);
  if (days <= 0) return "later today";
  if (days === 1) return "tomorrow";
  if (days <= WEEKDAY_WINDOW_DAYS) return `on ${shortWeekday(at)}`;
  return `on ${MONTHS[at.getMonth()]} ${at.getDate()}`;
}

function notesTask(sources: LibrarySource[], now: Date): NotesTask | null {
  const refresher = todayRefresher(sources, now);
  if (refresher === null) return null;
  if (refresher.kind === "done") return { status: DONE, refreshed: refresher.refreshed, next: refresher.next };
  return { status: refresher.position === 1 ? PENDING : IN_PROGRESS, refresher };
}

/**
 * An open quiz is waiting. Once none is open, the quiz whose last answer came today is done (it shows only on that
 * day): its answered cards, and how many of them were got right.
 */
function quizTask({ reviewData, reviews, now }: TodayInputs): QuizTask | null {
  const offer = quizOffer(reviewData, now);
  if (offer) return { status: PENDING, count: offer.count, until: offer.until };

  const answered = reviewData.cards.filter(
    (card) => card.kind === QUIZ_KIND && card.deletedAt === null && card.lastReviewAt !== null,
  );
  const last = answered.reduce<(typeof answered)[number] | null>(
    (latest, card) => (latest === null || card.lastReviewAt! > latest.lastReviewAt! ? card : latest),
    null,
  );
  if (last === null || !sameLocalDay(last.lastReviewAt!, now)) return null;

  // One week's quiz cards share their expiry.
  const quiz = answered.filter((card) => card.expiresAt === last.expiresAt);
  const gotIt = quiz.filter((card) => latestGrade(reviews, card.id) === GOT_IT).length;
  return { status: DONE, gotIt, answered: quiz.length };
}

function latestGrade(reviews: ReviewLogRow[], cardId: string): string | null {
  const own = reviews.filter((review) => review.cardId === cardId);
  const latest = own.reduce<ReviewLogRow | null>(
    (best, review) => (best === null || review.reviewedAt > best.reviewedAt ? review : best),
    null,
  );
  return latest?.grade ?? null;
}

/** The open (or being written) brief is waiting; with none, a brief finished today is done. */
function briefTask({ briefs, sources, now }: TodayInputs): BriefTask | null {
  const current = todayBrief(briefs, sources);
  if (current) return { status: PENDING, brief: current };

  const finished = briefs
    .filter((brief) => brief.doneAt !== null && sameLocalDay(brief.doneAt, now))
    .sort((first, second) => second.doneAt!.localeCompare(first.doneAt!))[0];
  if (!finished) return null;

  const content = parseBriefContent(finished.content);
  return { status: DONE, stories: content ? storiesInOrder(content).length : 0 };
}

// Cards not due yet that come due before tomorrow ends.
function dueByTomorrow(data: ReviewData, now: Date): number {
  const dayAfterTomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 2).getTime();
  return data.cards.filter((card) => isReviewable(card, data, now) && !isDue(card, now) && effectiveDue(card) < dayAfterTomorrow)
    .length;
}
