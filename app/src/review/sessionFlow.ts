// The review session's decisions, kept free of native modules so they can be tested: where a submitted answer goes,
// how a grading call is timed out, what each review records, and the Done screen's summary line.
import type { ReviewInput } from "@/db/actions";

import { applyGrade, knewItState } from "./schedule";
import { cardsWord } from "./labels";
import { SESSION_MODES, type SessionMode } from "./session";
import { dayWord } from "./summary";
import { type CardRow, type FsrsFields, fsrsFieldsOf, type GradedBy, type ReviewGrade } from "./types";

export const OFFLINE_REASON = "Offline · grading yourself · syncs later";
export const GRADE_FAILED_REASON = "Couldn't grade this one. How did you do?";

const GRADES: readonly ReviewGrade[] = ["got_it", "partly", "missed"];
// The server refuses longer recordings (413); the phone's own clock can run a little past the auto-stop.
const MAX_UPLOAD_DURATION_MS = 125_000;

export type NetworkLike = { isConnected?: boolean | null; isInternetReachable?: boolean | null };
export type Verdict = { grade: ReviewGrade; missing: string };
export type SubmitRoute = { kind: "grade" } | { kind: "self"; reason: string | null };
// What "I actually knew it" needs from the review it replaces.
export type RecordedReview = { reviewId: string; stateBefore: FsrsFields; reviewedAt: string; wasDue: boolean };

/** Offline only when the phone says so; an unknown state (before the first network reading) counts as online. */
export function isOffline(network: NetworkLike): boolean {
  return network.isConnected === false || network.isInternetReachable === false;
}

/** An empty box goes straight to self-grading; offline self-grades with a reason; otherwise the model grades. */
export function submitRoute(answer: string, network: NetworkLike): SubmitRoute {
  if (answer.trim() === "") return { kind: "self", reason: null };
  if (isOffline(network)) return { kind: "self", reason: OFFLINE_REASON };
  return { kind: "grade" };
}

/** The grade endpoint's body, or null when it isn't one (treated like any other grading failure). */
export function parseVerdict(body: unknown): Verdict | null {
  if (typeof body !== "object" || body === null) return null;
  const { grade, missing } = body as { grade?: unknown; missing?: unknown };
  if (!GRADES.includes(grade as ReviewGrade) || typeof missing !== "string") return null;
  return { grade: grade as ReviewGrade, missing };
}

/**
 * Runs the grading call, aborting it after `timeoutMs` or when `outer` aborts (the card was left). Null on timeout,
 * abort, failure or a malformed body; a response that lands after either is ignored, since the session has already
 * moved on.
 */
export async function gradeWithin(
  call: (signal: AbortSignal) => Promise<unknown>,
  timeoutMs: number,
  outer?: AbortSignal,
): Promise<Verdict | null> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<null>((resolve) => {
    const giveUp = (): void => {
      controller.abort();
      resolve(null);
    };
    timer = setTimeout(giveUp, timeoutMs);
    if (outer?.aborted) giveUp();
    else outer?.addEventListener("abort", giveUp, { once: true });
  });
  const attempt = call(controller.signal).then(parseVerdict, () => null);

  try {
    return await Promise.race([attempt, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Whether the 🎙 button shows. Offline it is hidden only while idle: a recording or transcription already under way
 * keeps its button, so the user can still stop it if the network drops mid-answer.
 */
export function micVisible(online: boolean, status: "idle" | "recording" | "transcribing"): boolean {
  return online || status !== "idle";
}

/** The review a grade records: the model's missing line only for partly/missed, never for a self-grade. */
export function reviewInputFor(
  card: CardRow,
  review: {
    grade: ReviewGrade;
    gradedBy: GradedBy;
    answer: string;
    missing: string | null;
    wasDue: boolean;
    now: Date;
  },
): ReviewInput {
  const stateBefore = fsrsFieldsOf(card);
  const keepsMissing = review.gradedBy === "model" && review.grade !== "got_it";
  return {
    cardId: card.id,
    grade: review.grade,
    gradedBy: review.gradedBy,
    answer: review.answer.trim() || null,
    missing: keepsMissing ? review.missing : null,
    wasDue: review.wasDue,
    reviewedAt: review.now,
    stateBefore,
    stateAfter: applyGrade({ ...stateBefore, kind: card.kind }, review.grade, review.now, review.wasDue),
  };
}

/** "I actually knew it": a self got_it that replaces `replaced`, scheduled from the state that review started from. */
export function knewItInput(card: CardRow, replaced: RecordedReview, answer: string, now: Date): ReviewInput {
  return {
    cardId: card.id,
    grade: "got_it",
    gradedBy: "self",
    answer: answer.trim() || null,
    missing: null,
    wasDue: replaced.wasDue,
    reviewedAt: now,
    stateBefore: replaced.stateBefore,
    stateAfter: knewItState(card.kind, replaced),
    replacesReviewId: replaced.reviewId,
  };
}

/** What a recorded review keeps for a later "I actually knew it". */
export function recordedReview(reviewId: string, input: ReviewInput): RecordedReview {
  return {
    reviewId,
    stateBefore: input.stateBefore,
    reviewedAt: input.reviewedAt.toISOString(),
    wasDue: input.wasDue,
  };
}

/** The first index at or after `from` whose card still exists; `ids.length` when none is left. */
export function nextLiveIndex(ids: readonly string[], from: number, isLive: (id: string) => boolean): number {
  const offset = ids.slice(from).findIndex(isLive);
  return offset === -1 ? ids.length : from + offset;
}

/** The route's `mode`; anything unknown is a due session. */
export function sessionModeOf(param: string | undefined): SessionMode {
  return SESSION_MODES.find((mode) => mode === param) ?? "due";
}

/** A transcript goes after what's already typed, separated by a space. */
export function appendTranscript(current: string, text: string): string {
  const spoken = text.trim();
  if (spoken === "") return current;
  return current.trim() === "" ? spoken : `${current.trimEnd()} ${spoken}`;
}

/** The recording length sent with the audio, within what the server accepts. */
export function uploadDurationMs(elapsedMs: number): number {
  return Math.min(MAX_UPLOAD_DURATION_MS, Math.max(1, Math.round(elapsedMs)));
}

/** Whole minutes since the session began, rounded up, at least 1. */
export function elapsedMinutes(startedAt: Date, now: Date): number {
  return Math.max(1, Math.ceil((now.getTime() - startedAt.getTime()) / 60_000));
}

/** "8 cards in 4 minutes. Next review tomorrow: 5 cards." (the second sentence only when something comes due). */
export function doneSummaryLine(
  graded: number,
  minutes: number,
  next: { at: Date; count: number } | null,
  now: Date,
): string {
  const done = `${cardsWord(graded)} in ${minutes} ${minutes === 1 ? "minute" : "minutes"}.`;
  if (next === null) return done;
  return `${done} Next review ${dayWord(next.at, now)}: ${cardsWord(next.count)}.`;
}
