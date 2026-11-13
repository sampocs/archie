import type { BriefContent, BriefRow } from "@/brief/brief";
import { noteSource } from "@/library/testRows";
import { cardRow, dayAt, reviewCard, reviewData } from "@/review/testCards";
import type { CardRow, ReviewRow } from "@/review/types";
import { todayTasks, tomorrowCounts, type TodayInputs } from "@/today/todayTasks";

import { widgetSnapshot } from "./widgetSnapshot";

// NOW is Thursday Nov 5 2026, noon (America/New_York, pinned by jest.config.js).
const NOW = new Date(2026, 10, 5, 12);

const review = (cardId: string): ReviewRow => ({
  id: `r-${cardId}`, cardId, grade: "got_it", gradedBy: "model", answer: null, missing: null, wasDue: 1,
  reviewedAt: dayAt(0, 9), stateBefore: "{}", stateAfter: "{}", replacesReviewId: null,
});

const brief = (overrides: Partial<BriefRow>): BriefRow => ({
  id: "b1", status: "open", content: JSON.stringify({ domains: [], also: [], essays: [] } satisfies BriefContent),
  sourceIds: "[]", since: null, version: 1, createdAt: dayAt(0, 6), updatedAt: dayAt(0, 6), doneAt: null,
  ...overrides,
});

const dueCard = (id: string): CardRow => reviewCard({ id, dueAt: dayAt(-1) });
const scheduled = (id: string, days: number): CardRow => reviewCard({ id, dueAt: dayAt(days, 9) });
const refreshed = (id: string, hour: number) =>
  noteSource({ id, refreshedAt: dayAt(0, hour), refreshedFromQueue: 1 });

function snapshotFor(overrides: Partial<Omit<TodayInputs, "reviewData">> & { cards?: CardRow[]; reviews?: ReviewRow[] }, now = NOW) {
  const { cards = [], reviews = [], ...rest } = overrides;
  const inputs: TodayInputs = {
    reviewData: reviewData(cards, { reviews }), reviews, sources: [], briefs: [], dailyLimit: null, now, ...rest,
  };
  const tasks = todayTasks(inputs);
  return widgetSnapshot(tasks, tomorrowCounts(inputs, tasks), now);
}

describe("today's rings", () => {
  it("are all null with nothing today", () => {
    expect(snapshotFor({}).days[0]).toEqual({ day: "2026-11-05", rings: { cards: null, notes: null, brief: null } });
  });

  it("are at 0 for every pending task", () => {
    const { rings } = snapshotFor({
      cards: [dueCard("a")], sources: [noteSource({ id: "n1" })], briefs: [brief({})],
    }).days[0];

    expect(rings).toEqual({
      cards: { progress: 0, done: false }, notes: { progress: 0, done: false }, brief: { progress: 0, done: false },
    });
  });

  it("fill in proportion to cards reviewed and notes refreshed while under way", () => {
    const cards = [dueCard("left"), scheduled("r1", 3), scheduled("r2", 3), scheduled("r3", 3)];
    const sources = [refreshed("done1", 9), noteSource({ id: "n2" })];

    const { rings } = snapshotFor({ cards, reviews: ["r1", "r2", "r3"].map(review), sources }).days[0];

    expect(rings.cards).toEqual({ progress: 0.75, done: false });
    expect(rings.notes).toEqual({ progress: 0.5, done: false });
  });

  it("are full and done once each task is done", () => {
    const sources = [refreshed("n1", 8), refreshed("n2", 9)];
    const briefs = [brief({ status: "done", doneAt: dayAt(0, 8) })];

    const { rings } = snapshotFor({ cards: [scheduled("r1", 3)], reviews: [review("r1")], sources, briefs }).days[0];

    const full = { progress: 1, done: true };
    expect(rings).toEqual({ cards: full, notes: full, brief: full });
  });
});

describe("tomorrow's rings", () => {
  const empty = { progress: 0, done: false };

  it("hold cards only when only cards are due by tomorrow", () => {
    expect(snapshotFor({ cards: [scheduled("t", 1)] }).days[1].rings).toEqual({ cards: empty, notes: null, brief: null });
  });

  it("hold notes only when only notes are queued", () => {
    const rings = snapshotFor({ sources: [noteSource({ id: "q1" })] }).days[1].rings;

    expect(rings).toEqual({ cards: null, notes: empty, brief: null });
  });

  it("hold a brief only after today's brief is done", () => {
    const done = snapshotFor({ briefs: [brief({ status: "done", doneAt: dayAt(0, 8) })] }).days[1].rings;
    const open = snapshotFor({ briefs: [brief({})] }).days[1].rings;

    expect(done).toEqual({ cards: null, notes: null, brief: empty });
    expect(open.brief).toBeNull();
  });

  it("are all null with nothing queued", () => {
    expect(snapshotFor({}).days[1].rings).toEqual({ cards: null, notes: null, brief: null });
  });
});

describe("day strings", () => {
  it("roll over a month boundary", () => {
    const snapshot = snapshotFor({}, new Date(2026, 9, 31, 12));

    expect(snapshot.days.map((entry) => entry.day)).toEqual(["2026-10-31", "2026-11-01"]);
  });

  it("roll over a year boundary", () => {
    expect(snapshotFor({}, new Date(2026, 11, 31, 23, 30)).days[1].day).toBe("2027-01-01");
  });
});
