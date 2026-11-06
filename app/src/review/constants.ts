// Review constants, verbatim from the M6 spec.

// How long the grader may take before the session falls back to self-grading.
export const GRADE_TIMEOUT_MS = 3000;
// "Review ahead" takes cards due within this many days.
export const AHEAD_DAYS = 3;
// The time estimate: about this long per card.
export const SECONDS_PER_CARD = 20;
export const MAX_RECORDING_MS = 120_000;
// Reminders are planned this many days out.
export const REMINDER_DAYS = 7;
