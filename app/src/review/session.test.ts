import { effectiveDue, isDue } from "./due";
import { buildSession, orderCards } from "./session";
import { cardRow, dayAt, NOW, reviewCard, reviewData, reviewRow, sourceRow, takeRow } from "./testCards";
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
      reviewCard({ id: "other", kind: "mystery", dueAt: dayAt(-20) }),
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
    const session = buildSession(data, "due", null, NOW, null);
    // other-source is new since Nov 1, so it has waited longest among the concepts.
    expect(ids(session)).toEqual(["primer-foundation", "other-source", "fresh", "overdue"]);
    expect(session.every(({ wasDue }) => wasDue)).toBe(true);
  });

  it("leaves a card that starts later out of every session until its start", () => {
    const waiting = cardRow({ id: "waiting", availableAt: dayAt(2) });
    const withWaiting = { ...data, cards: [...data.cards, waiting] };

    expect(ids(buildSession(withWaiting, "due", null, NOW, null))).not.toContain("waiting");
    expect(ids(buildSession(withWaiting, "ahead", null, NOW, null))).not.toContain("waiting");
    expect(ids(buildSession(withWaiting, "source", "s1", NOW, null))).not.toContain("waiting");
    expect(ids(buildSession(withWaiting, "due", null, new Date(dayAt(2)), null))).toContain("waiting");
  });

  it("ahead mode: only cards due within 3 days and not due now, none of them due", () => {
    const session = buildSession(data, "ahead", null, NOW, null);
    expect(session).toEqual([{ card: inTwoDays, wasDue: false }]);
  });

  it("topic mode: the topic's source cards and topic-primer foundation cards", () => {
    const session = buildSession(data, "topic", "t1", NOW, null);
    expect(ids(session)).toEqual(["primer-foundation", "foundation", "fresh", "overdue", "in-two-days", "in-four-days"]);
    expect(session.find(({ card }) => card.id === "foundation")?.wasDue).toBe(false);
    expect(session.find(({ card }) => card.id === "overdue")?.wasDue).toBe(true);
    expect(buildSession(data, "topic", null, NOW, null)).toEqual([]);
  });

  it("source mode: the source's cards, foundation cards included", () => {
    expect(ids(buildSession(data, "source", "s1", NOW, null))).toEqual([
      "foundation",
      "fresh",
      "overdue",
      "in-two-days",
      "in-four-days",
    ]);
    expect(buildSession(data, "source", null, NOW, null)).toEqual([]);
  });

  it("card mode: the one card, or none when it isn't reviewable", () => {
    expect(buildSession(data, "card", "in-four-days", NOW, null)).toEqual([{ card: inFourDays, wasDue: false }]);
    expect(buildSession(data, "card", "not-reviewable", NOW, null)).toEqual([]);
  });

  describe("take cards", () => {
    const takeCard = (id: string, takeId: string, overrides: Partial<CardRow> = {}): CardRow =>
      cardRow({ id, sourceId: null, takeId, kind: "take", createdAt: dayAt(-4), ...overrides });
    const takeData = reviewData(
      [
        overdue,
        foundation,
        reviewCard({ id: "number", kind: "number", dueAt: dayAt(-6) }),
        takeCard("take-new", "k1"),
        takeCard("take-later", "k1", { fsrsState: "review", dueAt: dayAt(5) }),
        takeCard("other-take", "k2"),
        takeCard("deleted-take", "k3"),
      ],
      {
        sources: [sourceRow({ id: "s1", state: "consumed", primerOpenedAt: dayAt(-3) })],
        takes: [takeRow({ id: "k1" }), takeRow({ id: "k2" }), takeRow({ id: "k3", deletedAt: dayAt(-1) })],
      },
    );

    it("take mode: only that take's reviewable cards", () => {
      expect(ids(buildSession(takeData, "take", "k1", NOW, null))).toEqual(["take-new", "take-later"]);
      expect(buildSession(takeData, "take", "k3", NOW, null)).toEqual([]);
      expect(buildSession(takeData, "take", null, NOW, null)).toEqual([]);
    });

    it("due mode: take cards sort with concepts, after foundations and before numbers", () => {
      // The foundation isn't due; the two new take cards waited longer than the overdue concept.
      expect(ids(buildSession(takeData, "due", null, NOW, null))).toEqual([
        "other-take",
        "take-new",
        "overdue",
        "number",
      ]);
    });
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

    const session = buildSession(quizData, "quiz", null, NOW, null);
    expect(ids(session)).toEqual(["earlier", "later"]);
    expect(session.every(({ wasDue }) => wasDue)).toBe(true);
  });

  describe("with a daily cap", () => {
    // c00 is the most overdue.
    const backlog = Array.from({ length: 25 }, (_, index) =>
      reviewCard({ id: `c${String(index).padStart(2, "0")}`, dueAt: dayAt(-30 + index) }),
    );
    const capped = reviewData(backlog);
    const sorted = (session: { card: CardRow }[]): string[] => ids(session).sort();
    const cardIds = (cards: CardRow[]): string[] => cards.map((card) => card.id).sort();

    it("due mode: only today's capped set, the most overdue cards", () => {
      expect(sorted(buildSession(capped, "due", null, NOW, 10))).toEqual(cardIds(backlog.slice(0, 10)));
    });

    it("more mode: the next batch of waiting cards, all due", () => {
      const more = buildSession(capped, "more", null, NOW, 10);

      expect(sorted(more)).toEqual(cardIds(backlog.slice(10, 20)));
      expect(more.every(({ wasDue }) => wasDue)).toBe(true);
    });

    it("more mode: after the cap is reviewed, the next batch starts at the most overdue left", () => {
      const reviews = backlog.slice(0, 10).map(({ id }) => reviewRow({ id: `review-${id}`, cardId: id }));
      const left = backlog.slice(10);
      const afterFirst = reviewData([...backlog.slice(0, 10).map((card) => ({ ...card, dueAt: dayAt(5) })), ...left], {
        reviews,
      });

      expect(buildSession(afterFirst, "due", null, NOW, 10)).toEqual([]);
      expect(sorted(buildSession(afterFirst, "more", null, NOW, 10))).toEqual(cardIds(left.slice(0, 10)));
    });
  });
});
