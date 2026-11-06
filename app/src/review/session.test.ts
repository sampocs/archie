import { buildSession, effectiveDue, isDue, orderCards } from "./session";
import { cardRow, dayAt, NOW, reviewCard, reviewData, sourceRow } from "./testCards";
import type { CardRow } from "./types";

const ids = (cards: { card: CardRow }[]): string[] => cards.map(({ card }) => card.id);

describe("isDue and effectiveDue", () => {
  it("a new card is due since it was made; a review card from its due date", () => {
    const fresh = cardRow({ createdAt: dayAt(-1) });
    expect(isDue(fresh, NOW)).toBe(true);
    expect(effectiveDue(fresh)).toBe(Date.parse(dayAt(-1)));

    expect(isDue(reviewCard({ dueAt: NOW.toISOString() }), NOW)).toBe(true);
    expect(isDue(reviewCard({ dueAt: dayAt(0, 12, 1) }), NOW)).toBe(false);
    expect(effectiveDue(reviewCard({ dueAt: dayAt(2) }))).toBe(Date.parse(dayAt(2)));
  });
});

describe("orderCards", () => {
  it("orders by kind group, then most overdue (new cards by createdAt), then id", () => {
    const cards = [
      reviewCard({ id: "number-overdue", kind: "number", dueAt: dayAt(-9) }),
      reviewCard({ id: "concept-recent-b", kind: "concept", dueAt: dayAt(-1) }),
      reviewCard({ id: "concept-recent", kind: "concept", dueAt: dayAt(-1) }),
      cardRow({ id: "mechanism-new", kind: "mechanism", createdAt: dayAt(-3) }),
      reviewCard({ id: "foundation-recent", kind: "foundation", dueAt: dayAt(-1) }),
      reviewCard({ id: "other", kind: "take", dueAt: dayAt(-20) }),
      reviewCard({ id: "concept-old", kind: "concept", dueAt: dayAt(-5) }),
      reviewCard({ id: "foundation-old", kind: "foundation", dueAt: dayAt(-2) }),
    ];

    expect(orderCards(cards).map((card) => card.id)).toEqual([
      "foundation-old",
      "foundation-recent",
      "concept-old",
      "mechanism-new",
      "concept-recent",
      "concept-recent-b",
      "number-overdue",
      "other",
    ]);
  });
});

describe("buildSession", () => {
  const overdue = reviewCard({ id: "overdue", dueAt: dayAt(-1) });
  const fresh = cardRow({ id: "fresh", createdAt: dayAt(-2) });
  const inTwoDays = reviewCard({ id: "in-two-days", dueAt: dayAt(2) });
  const inFourDays = reviewCard({ id: "in-four-days", dueAt: dayAt(4) });
  const foundation = reviewCard({ id: "foundation", kind: "foundation", dueAt: dayAt(10) });
  const primerFoundation = cardRow({ id: "primer-foundation", sourceId: null, topicPrimerId: "p1", kind: "foundation" });
  const otherSource = cardRow({ id: "other-source", sourceId: "s2" });
  const notReviewable = cardRow({ id: "not-reviewable", sourceId: "s3" });
  const data = reviewData([overdue, fresh, inTwoDays, inFourDays, foundation, primerFoundation, otherSource, notReviewable], {
    sources: [
      sourceRow({ id: "s1", state: "consumed", primerOpenedAt: dayAt(-3), topicId: "t1" }),
      sourceRow({ id: "s2", state: "consumed", topicId: "t2" }),
      sourceRow({ id: "s3", state: "inbox", topicId: "t1" }),
    ],
  });

  it("due mode: new and overdue reviewable cards, in order", () => {
    const session = buildSession(data, "due", null, NOW);
    // other-source is new since Nov 1, so it has waited longest among the concepts.
    expect(ids(session)).toEqual(["primer-foundation", "other-source", "fresh", "overdue"]);
    expect(session.every(({ wasDue }) => wasDue)).toBe(true);
  });

  it("ahead mode: only cards due within 3 days and not due now, none of them due", () => {
    const session = buildSession(data, "ahead", null, NOW);
    expect(session).toEqual([{ card: inTwoDays, wasDue: false }]);
  });

  it("topic mode: the topic's source cards and topic-primer foundation cards", () => {
    const session = buildSession(data, "topic", "t1", NOW);
    expect(ids(session)).toEqual(["primer-foundation", "foundation", "fresh", "overdue", "in-two-days", "in-four-days"]);
    expect(session.find(({ card }) => card.id === "foundation")?.wasDue).toBe(false);
    expect(session.find(({ card }) => card.id === "overdue")?.wasDue).toBe(true);
    expect(buildSession(data, "topic", null, NOW)).toEqual([]);
  });

  it("source mode: the source's cards, foundation cards included", () => {
    expect(ids(buildSession(data, "source", "s1", NOW))).toEqual([
      "foundation",
      "fresh",
      "overdue",
      "in-two-days",
      "in-four-days",
    ]);
    expect(buildSession(data, "source", null, NOW)).toEqual([]);
  });

  it("card mode: the one card, or none when it isn't reviewable", () => {
    expect(buildSession(data, "card", "in-four-days", NOW)).toEqual([{ card: inFourDays, wasDue: false }]);
    expect(buildSession(data, "card", "not-reviewable", NOW)).toEqual([]);
  });

  it("quiz mode: open quiz cards by createdAt", () => {
    const quiz = (id: string, createdAt: string, overrides: Partial<CardRow> = {}): CardRow =>
      cardRow({ id, sourceId: null, briefId: "b1", kind: "quiz", createdAt, expiresAt: dayAt(3), ...overrides });
    const quizData = reviewData([
      quiz("later", dayAt(-1)),
      quiz("earlier", dayAt(-2)),
      quiz("answered", dayAt(-3), { lastReviewAt: dayAt(-1) }),
      quiz("expired", dayAt(-8), { expiresAt: dayAt(-1) }),
      overdue,
    ]);

    const session = buildSession(quizData, "quiz", null, NOW);
    expect(ids(session)).toEqual(["earlier", "later"]);
    expect(session.every(({ wasDue }) => wasDue)).toBe(true);
  });
});
