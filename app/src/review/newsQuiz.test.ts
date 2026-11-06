import { quizOffer, weekStartFor } from "./newsQuiz";
import { cardRow, dayAt, NOW, reviewData } from "./testCards";

describe("weekStartFor", () => {
  it.each([
    [new Date(2026, 10, 8, 9), "2026-11-08"],
    [new Date(2026, 10, 7, 23, 59), null],
    // 04:30 UTC Monday, still Sunday on the phone.
    [new Date(2026, 10, 8, 23, 30), "2026-11-08"],
  ])("%s → %p", (now, expected) => {
    expect(weekStartFor(now)).toBe(expected);
  });
});

describe("quizOffer", () => {
  const quiz = (id: string, expiresAt: string, lastReviewAt: string | null = null) =>
    cardRow({ id, sourceId: null, briefId: "b1", kind: "quiz", expiresAt, lastReviewAt });

  it("counts open quiz cards until the earliest expiry", () => {
    const data = reviewData([
      quiz("q1", dayAt(5)),
      quiz("q2", dayAt(3)),
      quiz("answered", dayAt(1), dayAt(-1)),
      quiz("expired", dayAt(-1)),
      cardRow({}),
    ]);

    expect(quizOffer(data, NOW)).toEqual({ count: 2, until: new Date(dayAt(3)) });
  });

  it("is null when no quiz is open", () => {
    expect(quizOffer(reviewData([quiz("expired", dayAt(-1))]), NOW)).toBeNull();
  });
});
