import { isOpenQuiz, type ReviewData } from "./eligibility";

const SUNDAY = 0;

/** The week a news quiz is asked for: today's local date "YYYY-MM-DD" on a Sunday, else null. */
export function weekStartFor(now: Date): string | null {
  return now.getDay() === SUNDAY ? localDate(now) : null;
}

/** The open quiz: how many cards are left and when the first of them expires; null when none is open. */
export function quizOffer(data: ReviewData, now: Date): { count: number; until: Date } | null {
  const open = data.cards.filter((card) => isOpenQuiz(card, now));
  if (open.length === 0) return null;
  // isOpenQuiz guarantees every open card has an expiry.
  return { count: open.length, until: new Date(Math.min(...open.map((card) => Date.parse(card.expiresAt!)))) };
}

function localDate(day: Date): string {
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}
