import * as Network from "expo-network";
import { useEffect, useRef, useState } from "react";

import { apiFetch } from "@/api/client";
import { reviewCard } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";

import { GRADE_TIMEOUT_MS } from "./constants";
import {
  GRADE_FAILED_REASON,
  gradeWithin,
  knewItInput,
  recordedReview,
  type RecordedReview,
  reviewInputFor,
  submitRoute,
} from "./sessionFlow";
import type { CardRow, ReviewGrade } from "./types";

export type GradePhase =
  | { kind: "answering" }
  | { kind: "grading"; answer: string }
  // `replaced` is the model's review "I actually knew it" would replace; null once it has been used (or for got_it).
  | { kind: "graded"; answer: string; grade: ReviewGrade; missing: string; replaced: RecordedReview | null }
  | { kind: "selfGrade"; answer: string; reason: string | null; chosen: ReviewGrade | null };

type GraderArgs = {
  card: CardRow;
  wasDue: boolean;
  sessionKey: string | null;
  // Every recorded grade, for the session's tally.
  onGraded: (cardId: string, grade: ReviewGrade) => void;
};

/**
 * One card's answer → grade flow. Every grade is written (and queued for sync) the moment it is known, so leaving the
 * session never loses one. The owner remounts the hook per card (a `key`), so nothing carries over between cards.
 */
export function useGrader({ card, wasDue, sessionKey, onGraded }: GraderArgs) {
  const [phase, setPhase] = useState<GradePhase>({ kind: "answering" });

  // The latest card and callback, for writes that happen after an await; `mounted` drops a grade that lands after
  // the card was left (✕ or Next while grading).
  const latest = useRef({ card, onGraded });
  latest.current = { card, onGraded };
  const mounted = useRef(true);
  const submitted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  function record(grade: ReviewGrade, gradedBy: "model" | "self", answer: string, missing: string): RecordedReview {
    const input = reviewInputFor(latest.current.card, { grade, gradedBy, answer, missing, wasDue, now: new Date() });
    const reviewId = reviewCard(db, input);
    requestSync();
    latest.current.onGraded(input.cardId, grade);
    return recordedReview(reviewId, input);
  }

  async function submit(answer: string): Promise<void> {
    if (submitted.current) return;
    submitted.current = true;

    // The network is read only for a typed answer: an empty box never needs the grader. An unreadable network state
    // counts as online; if it isn't, the grading call fails and the user grades themselves anyway.
    const network = answer.trim() === "" ? {} : await Network.getNetworkStateAsync().catch(() => ({}));
    const route = submitRoute(answer, network);
    if (!mounted.current) return;
    if (route.kind === "self") {
      setPhase({ kind: "selfGrade", answer, reason: route.reason, chosen: null });
      return;
    }

    setPhase({ kind: "grading", answer });
    const verdict = await gradeWithin(
      (signal) =>
        apiFetch("/review/grade", {
          method: "POST",
          body: { card_id: latest.current.card.id, answer: answer.trim() },
          sessionKey,
          signal,
        }),
      GRADE_TIMEOUT_MS,
    );
    if (!mounted.current) return;
    if (verdict === null) {
      setPhase({ kind: "selfGrade", answer, reason: GRADE_FAILED_REASON, chosen: null });
      return;
    }

    const recorded = record(verdict.grade, "model", answer, verdict.missing);
    if (verdict.grade === "got_it") haptic("success");
    const replaced = verdict.grade === "got_it" ? null : recorded;
    setPhase({ kind: "graded", answer, grade: verdict.grade, missing: verdict.missing, replaced });
  }

  function selfGrade(grade: ReviewGrade): void {
    if (phase.kind !== "selfGrade" || phase.chosen !== null) return;
    haptic("selection");
    record(grade, "self", phase.answer, "");
    setPhase({ ...phase, chosen: grade });
  }

  // "I actually knew it": a self got_it replacing the model's review, scheduled from where that review started.
  function knewIt(): void {
    if (phase.kind !== "graded" || phase.replaced === null) return;
    const input = knewItInput(latest.current.card, phase.replaced, phase.answer, new Date());
    reviewCard(db, input);
    requestSync();
    latest.current.onGraded(input.cardId, "got_it");
    haptic("success");
    setPhase({ ...phase, grade: "got_it", replaced: null });
  }

  return { phase, submit, selfGrade, knewIt };
}
