import { applyGrade, knewItState } from "./schedule";
import { cardRow, dayAt, NOW, reviewCard } from "./testCards";
import { fsrsFieldsOf, type FsrsFields } from "./types";

const fields = (overrides: Parameters<typeof reviewCard>[0]): FsrsFields => fsrsFieldsOf(reviewCard(overrides));
const concept = (state: FsrsFields) => ({ ...state, kind: "concept" });

describe("applyGrade", () => {
  it("schedules a new card graded got_it into review", () => {
    const after = applyGrade(concept(fsrsFieldsOf(cardRow({}))), "got_it", NOW, true);

    expect(after.fsrsState).toBe("review");
    expect(Date.parse(after.dueAt!)).toBeGreaterThan(NOW.getTime());
    expect(after.reps).toBe(1);
    expect(after.lastReviewAt).toBe(NOW.toISOString());
  });

  it("counts a lapse on a missed review card and brings it sooner than got_it would", () => {
    const due = fields({ dueAt: dayAt(-1) });

    const missed = applyGrade(concept(due), "missed", NOW, true);
    const gotIt = applyGrade(concept(due), "got_it", NOW, true);

    expect(missed.lapses).toBe(due.lapses + 1);
    expect(Date.parse(missed.dueAt!)).toBeLessThan(Date.parse(gotIt.dueAt!));
  });

  it("leaves a card that wasn't due unchanged on got_it", () => {
    const notDue = fields({ dueAt: dayAt(5) });

    expect(applyGrade(concept(notDue), "got_it", NOW, false)).toEqual(notDue);
  });

  it("never moves a card that wasn't due later on partly", () => {
    const notDue = fields({ dueAt: dayAt(30), stability: 60, lastReviewAt: dayAt(-30) });

    const after = applyGrade(concept(notDue), "partly", NOW, false);

    expect(Date.parse(after.dueAt!)).toBeLessThanOrEqual(Date.parse(notDue.dueAt!));
    expect(after.reps).toBe(notDue.reps + 1);
    expect(after.lastReviewAt).toBe(NOW.toISOString());
  });

  it("clamps exactly where FSRS alone would push a not-due card later", () => {
    const notDue = fields({ dueAt: dayAt(1), stability: 60, lastReviewAt: dayAt(-30) });

    const unclamped = applyGrade(concept(notDue), "partly", NOW, true);
    const clamped = applyGrade(concept(notDue), "partly", NOW, false);

    expect(Date.parse(unclamped.dueAt!)).toBeGreaterThan(Date.parse(notDue.dueAt!));
    expect(clamped).toEqual({ ...unclamped, dueAt: notDue.dueAt });
  });

  it("brings a card that wasn't due sooner on missed", () => {
    const notDue = fields({ dueAt: dayAt(30), stability: 60, lastReviewAt: dayAt(-30) });

    const after = applyGrade(concept(notDue), "missed", NOW, false);

    expect(Date.parse(after.dueAt!)).toBeLessThan(Date.parse(notDue.dueAt!));
    expect(after.lapses).toBe(notDue.lapses + 1);
  });

  it("only marks a quiz card answered", () => {
    const quiz = fsrsFieldsOf(cardRow({ kind: "quiz" }));

    expect(applyGrade({ ...quiz, kind: "quiz" }, "missed", NOW, true)).toEqual({
      ...quiz,
      lastReviewAt: NOW.toISOString(),
    });
  });
});

describe("knewItState", () => {
  const stateBefore = fields({ dueAt: dayAt(-2) });
  const reviewedAt = NOW.toISOString();

  it("redoes a due review as got_it from the state it started from", () => {
    const knew = knewItState("concept", { stateBefore, reviewedAt, wasDue: true });

    expect(knew).toEqual(applyGrade(concept(stateBefore), "got_it", NOW, true));
    expect(knew).not.toEqual(applyGrade(concept(stateBefore), "missed", NOW, true));
  });

  it("restores the starting state when the replaced review wasn't due", () => {
    const notDue = fields({ dueAt: dayAt(4) });

    expect(knewItState("concept", { stateBefore: notDue, reviewedAt, wasDue: false })).toEqual(notDue);
  });
});
