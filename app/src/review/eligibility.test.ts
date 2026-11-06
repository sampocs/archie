import { cardDomain, cardOrigin, cardTopicId, isOpenQuiz, isReviewable } from "./eligibility";
import { cardRow, dayAt, NOW, reviewData, sourceRow, topicPrimerRow, topicRow } from "./testCards";

const primerCard = cardRow({ id: "f1", sourceId: null, topicPrimerId: "p1", kind: "foundation" });

describe("isReviewable", () => {
  it.each([
    ["queued", "inbox", false],
    ["consumed", "consumed", true],
  ])("a summary card of a %s source: %p", (_, state, expected) => {
    const data = reviewData([], { sources: [sourceRow({ id: "s1", state })] });
    expect(isReviewable(cardRow({}), data)).toBe(expected);
  });

  it.each([
    [null, false],
    ["2026-11-02T00:00:00Z", true],
  ])("a source foundation card with primerOpenedAt %p: %p", (primerOpenedAt, expected) => {
    const data = reviewData([], { sources: [sourceRow({ id: "s1", state: "consumed", primerOpenedAt })] });
    expect(isReviewable(cardRow({ kind: "foundation" }), data)).toBe(expected);
  });

  it("a source's foundation cards don't wait for it to be consumed", () => {
    const data = reviewData([], { sources: [sourceRow({ id: "s1", state: "inbox", primerOpenedAt: dayAt(-1) })] });
    expect(isReviewable(cardRow({ kind: "foundation" }), data)).toBe(true);
  });

  it("a card of a deleted or missing source is not", () => {
    const deleted = reviewData([], { sources: [sourceRow({ id: "s1", state: "consumed", deletedAt: dayAt(-1) })] });
    expect(isReviewable(cardRow({}), deleted)).toBe(false);
    expect(isReviewable(cardRow({}), reviewData([], { sources: [] }))).toBe(false);
  });

  it("a topic-primer foundation card once the primer is opened and the topic is live", () => {
    expect(isReviewable(primerCard, reviewData([]))).toBe(true);
    expect(isReviewable(primerCard, reviewData([], { topicPrimers: [topicPrimerRow({ id: "p1" })] }))).toBe(false);
    expect(isReviewable(primerCard, reviewData([], { topics: [topicRow({ id: "t1", removedAt: dayAt(-1) })] }))).toBe(
      false,
    );
    expect(isReviewable(primerCard, reviewData([], { topics: [topicRow({ id: "t1", mergedIntoId: "t2" })] }))).toBe(
      false,
    );
    expect(isReviewable(primerCard, reviewData([], { topicPrimers: [] }))).toBe(false);
  });

  it("a deleted card is not", () => {
    expect(isReviewable(cardRow({ deletedAt: dayAt(-1) }), reviewData([]))).toBe(false);
  });

  it("a quiz card or a card with no origin is not", () => {
    const quiz = cardRow({ sourceId: null, briefId: "b1", kind: "quiz" });
    expect(isReviewable(quiz, reviewData([]))).toBe(false);
    expect(isReviewable(cardRow({ sourceId: null }), reviewData([]))).toBe(false);
  });
});

describe("isOpenQuiz", () => {
  const quiz = cardRow({ sourceId: null, briefId: "b1", kind: "quiz", expiresAt: dayAt(2) });

  it("is open until it expires or is answered", () => {
    expect(isOpenQuiz(quiz, NOW)).toBe(true);
    expect(isOpenQuiz(quiz, new Date(dayAt(2)))).toBe(false);
    expect(isOpenQuiz({ ...quiz, lastReviewAt: NOW.toISOString() }, NOW)).toBe(false);
    expect(isOpenQuiz({ ...quiz, deletedAt: NOW.toISOString() }, NOW)).toBe(false);
    expect(isOpenQuiz({ ...quiz, expiresAt: null }, NOW)).toBe(false);
    expect(isOpenQuiz({ ...quiz, kind: "concept" }, NOW)).toBe(false);
  });
});

describe("card origin, topic and domain", () => {
  it("follows the card's origin", () => {
    const data = reviewData([], { topics: [topicRow({ id: "t1", domain: "Economics" })] });
    const briefCard = cardRow({ sourceId: null, briefId: "b1", kind: "quiz" });

    expect(cardOrigin(cardRow({}))).toEqual({ kind: "source", sourceId: "s1" });
    expect(cardOrigin(primerCard)).toEqual({ kind: "topicPrimer", topicPrimerId: "p1" });
    expect(cardOrigin(briefCard)).toEqual({ kind: "brief", briefId: "b1" });
    expect(cardOrigin(cardRow({ sourceId: null }))).toEqual({ kind: "unknown" });

    expect([cardTopicId(cardRow({}), data), cardDomain(cardRow({}), data)]).toEqual(["t1", "AI"]);
    expect([cardTopicId(primerCard, data), cardDomain(primerCard, data)]).toEqual(["t1", "Economics"]);
    expect([cardTopicId(briefCard, data), cardDomain(briefCard, data)]).toEqual([null, null]);
    expect(cardTopicId(cardRow({ sourceId: "gone" }), data)).toBeNull();
    expect(cardDomain(primerCard, reviewData([], { topicPrimers: [] }))).toBeNull();
  });
});
