import { dailyPlan, reviewedDueToday, stepDailyLimit } from "./dailyCap";
import { cardRow, dayAt, NOW, reviewCard, reviewData, reviewRow } from "./testCards";
import type { CardRow } from "./types";

// Reviews due `days` ago (more negative = more overdue) and new cards that arrived `days` ago.
const overdue = (id: string, days: number): CardRow => reviewCard({ id, dueAt: dayAt(days) });
const fresh = (id: string, days: number): CardRow => cardRow({ id, createdAt: dayAt(days) });
const ids = (cards: CardRow[]): string[] => cards.map((card) => card.id).sort();
const range = (prefix: string, count: number, make: (id: string, index: number) => CardRow): CardRow[] =>
  Array.from({ length: count }, (_, index) => make(`${prefix}${String(index).padStart(2, "0")}`, index));

describe("dailyPlan", () => {
  it("puts every due card in today's set when they fit under the cap", () => {
    const cards = [overdue("a", -1), fresh("b", -2), reviewCard({ id: "later", dueAt: dayAt(2) })];
    const plan = dailyPlan(reviewData(cards), 20, NOW);

    expect(ids(plan.today)).toEqual(["a", "b"]);
    expect(plan.waiting).toEqual([]);
    expect(plan.budget).toBe(20);
  });

  it("over the cap, takes reviews earliest due first", () => {
    // r00 is the most overdue, r24 the least.
    const cards = range("r", 25, (id, index) => overdue(id, -30 + index));
    const plan = dailyPlan(reviewData(cards), 20, NOW);

    expect(ids(plan.today)).toEqual(ids(cards.slice(0, 20)));
    expect(ids(plan.waiting)).toEqual(ids(cards.slice(20)));
  });

  it("keeps 5 slots for the earliest-arrived new cards behind a review backlog", () => {
    const reviews = range("r", 30, (id, index) => overdue(id, -40 + index));
    const news = range("n", 8, (id, index) => fresh(id, -10 + index));
    const plan = dailyPlan(reviewData([...reviews, ...news]), 20, NOW);

    expect(ids(plan.today)).toEqual(ids([...news.slice(0, 5), ...reviews.slice(0, 15)]));
  });

  it("orders new cards by when they became available, not when they were made", () => {
    const early = cardRow({ id: "made-late-released-early", createdAt: dayAt(-1), availableAt: dayAt(-9) });
    const news = [...range("n", 5, (id) => fresh(id, -5)), early];
    const plan = dailyPlan(reviewData([...news, ...range("r", 20, (id) => overdue(id, -1))]), 10, NOW);

    expect(ids(plan.today)).toContain("made-late-released-early");
    expect(ids(plan.today)).not.toContain("n04");
  });

  it("gives slots reviews can't fill back to new cards", () => {
    const reviews = range("r", 3, (id) => overdue(id, -1));
    const news = range("n", 20, (id, index) => fresh(id, -30 + index));
    const plan = dailyPlan(reviewData([...reviews, ...news]), 10, NOW);

    expect(ids(plan.today)).toEqual(ids([...news.slice(0, 7), ...reviews]));
    expect(plan.waiting).toHaveLength(13);
  });

  it("shrinks the budget by distinct due cards reviewed today, not counting quiz answers or re-grades", () => {
    const due = range("d", 10, (id) => overdue(id, -1));
    const done = ["x1", "x2"].map((id) => reviewCard({ id, dueAt: dayAt(3) }));
    const quiz = cardRow({ id: "q1", sourceId: null, briefId: "b1", kind: "quiz", expiresAt: dayAt(2) });
    const reviews = [
      reviewRow({ id: "a", cardId: "x1", reviewedAt: dayAt(0, 9) }),
      reviewRow({ id: "b", cardId: "x1", reviewedAt: dayAt(0, 9, 5), replacesReviewId: "a" }),
      reviewRow({ id: "c", cardId: "x2", reviewedAt: dayAt(0, 10) }),
      reviewRow({ id: "d", cardId: "q1", reviewedAt: dayAt(0, 10) }),
      reviewRow({ id: "e", cardId: "x2", reviewedAt: dayAt(-1, 10) }),
      reviewRow({ id: "f", cardId: "d00", reviewedAt: dayAt(0, 8), wasDue: 0 }),
    ];
    const data = reviewData([...due, ...done, quiz], { reviews });

    expect(reviewedDueToday(data, reviews, NOW)).toBe(2);
    const plan = dailyPlan(data, 10, NOW);
    expect(plan.budget).toBe(8);
    expect(plan.today).toHaveLength(8);
    expect(plan.waiting).toHaveLength(2);
  });

  it("with the budget used up, shows nothing today and leaves every due card waiting", () => {
    const done = range("x", 10, (id) => reviewCard({ id, dueAt: dayAt(3) }));
    const reviews = done.map(({ id }) => reviewRow({ id: `review-${id}`, cardId: id, reviewedAt: dayAt(0, 9) }));
    const plan = dailyPlan(reviewData([...done, overdue("left", -1), fresh("new", -1)], { reviews }), 10, NOW);

    expect(plan.budget).toBe(0);
    expect(plan.today).toEqual([]);
    expect(ids(plan.waiting)).toEqual(["left", "new"]);
  });

  it("with the cap off, shows every due card and leaves none waiting", () => {
    const cards = [...range("r", 40, (id) => overdue(id, -1)), ...range("n", 20, (id) => fresh(id, -1))];
    const plan = dailyPlan(reviewData(cards), null, NOW);

    expect(plan.today).toHaveLength(60);
    expect(plan.waiting).toEqual([]);
    expect(plan.budget).toBeNull();
  });
});

describe("stepDailyLimit", () => {
  it("steps by 5 between 10 and 50, past 50 to Off, and stops at the ends", () => {
    expect(stepDailyLimit(20, 1)).toEqual({ value: 25 });
    expect(stepDailyLimit(50, 1)).toEqual({ value: null });
    expect(stepDailyLimit(null, -1)).toEqual({ value: 50 });
    expect(stepDailyLimit(10, -1)).toBeNull();
    expect(stepDailyLimit(null, 1)).toBeNull();
  });
});
