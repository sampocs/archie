import {
  aheadSummary,
  cardDueLabel,
  dayWord,
  dueSummary,
  minutesFor,
  nextReview,
  shortWeekday,
  topicPractice,
} from "./summary";
import { cardRow, dayAt, NOW, reviewCard, reviewData, sourceRow, takeRow, topicRow } from "./testCards";

describe("minutesFor", () => {
  it.each([
    [0, 1],
    [3, 1],
    [4, 2],
    [12, 4],
  ])("%p cards → %p min", (count, minutes) => {
    expect(minutesFor(count)).toBe(minutes);
  });
});

describe("dueSummary and aheadSummary", () => {
  const data = reviewData([
    cardRow({ id: "new-concept" }),
    reviewCard({ id: "due-foundation", kind: "foundation", dueAt: dayAt(-1) }),
    reviewCard({ id: "ahead", dueAt: dayAt(1) }),
    reviewCard({ id: "later", dueAt: dayAt(5) }),
  ]);

  it("counts due cards and how many are foundations", () => {
    expect(dueSummary(data, NOW)).toEqual({ count: 2, foundations: 1 });
  });

  it("counts cards due within the ahead window", () => {
    expect(aheadSummary(data, NOW)).toEqual({ count: 1, by: new Date(dayAt(3)) });
  });
});

describe("nextReview", () => {
  it("picks the next due day and counts that day's cards", () => {
    const data = reviewData([
      cardRow({ id: "due-now" }),
      reviewCard({ id: "tomorrow-late", dueAt: dayAt(1, 23, 30) }),
      reviewCard({ id: "tomorrow-morning", dueAt: dayAt(1, 9) }),
      reviewCard({ id: "saturday", dueAt: dayAt(2, 0, 30) }),
      reviewCard({ id: "unreviewable", sourceId: "s9", dueAt: dayAt(1, 8) }),
    ]);

    expect(nextReview(data, NOW)).toEqual({ at: new Date(dayAt(1, 9)), count: 2 });
  });

  it("is null when nothing is waiting", () => {
    expect(nextReview(reviewData([cardRow({})]), NOW)).toBeNull();
  });
});

describe("dayWord and shortWeekday", () => {
  it.each([
    [dayAt(0, 23), "today"],
    [dayAt(1, 0, 5), "tomorrow"],
    [dayAt(2), "Saturday"],
    [dayAt(6, 23), "Wednesday"],
    [dayAt(7, 1), "Nov 12"],
  ])("%s → %p", (day, word) => {
    expect(dayWord(new Date(day), NOW)).toBe(word);
  });

  it("names the weekday briefly", () => {
    expect(shortWeekday(new Date(dayAt(2)))).toBe("Sat");
  });
});

describe("cardDueLabel", () => {
  const data = reviewData([], { takes: [takeRow({ id: "k1" })] });

  it.each([
    ["a new card", cardRow({}), "Due today"],
    ["an overdue card", reviewCard({ dueAt: dayAt(-4) }), "Due today"],
    ["a card due later today", reviewCard({ dueAt: dayAt(0, 23, 59) }), "Due today"],
    ["a card due tomorrow", reviewCard({ dueAt: dayAt(1, 0, 1) }), "Due tomorrow"],
    ["a card due Saturday", reviewCard({ dueAt: dayAt(2) }), "Due Sat"],
    ["a card due in 6 days", reviewCard({ dueAt: dayAt(6, 23) }), "Due Wed"],
    ["a card due in 7 days", reviewCard({ dueAt: dayAt(7, 1) }), "Due in 7 days"],
    ["a card not yet reviewable", cardRow({ sourceId: "s9" }), "After you finish"],
    ["a new take card, reviewable at once", cardRow({ sourceId: null, takeId: "k1", kind: "take" }), "Due today"],
  ])("%s → %p", (_, card, label) => {
    expect(cardDueLabel(card, data, NOW)).toBe(label);
  });
});

describe("topicPractice", () => {
  it("counts each live topic's reviewable cards, busiest first, then by name", () => {
    const data = reviewData(
      [
        cardRow({ id: "a1", sourceId: "sa" }),
        cardRow({ id: "b1", sourceId: "sb" }),
        cardRow({ id: "b2", sourceId: "sb" }),
        cardRow({ id: "c1", sourceId: "sc" }),
        cardRow({ id: "unreviewable", sourceId: "sd" }),
        cardRow({ id: "removed", sourceId: "se" }),
      ],
      {
        sources: [
          sourceRow({ id: "sa", state: "consumed", topicId: "ta" }),
          sourceRow({ id: "sb", state: "consumed", topicId: "tb" }),
          sourceRow({ id: "sc", state: "consumed", topicId: "tc" }),
          sourceRow({ id: "sd", state: "inbox", topicId: "td" }),
          sourceRow({ id: "se", state: "consumed", topicId: "te" }),
        ],
        topics: [
          topicRow({ id: "tc", name: "Chips" }),
          topicRow({ id: "ta", name: "Agents" }),
          topicRow({ id: "tb", name: "Batteries" }),
          topicRow({ id: "td", name: "Drones" }),
          topicRow({ id: "te", name: "Energy", removedAt: dayAt(-1) }),
        ],
      },
    );

    expect(topicPractice(data).map(({ topic, count }) => [topic.name, count])).toEqual([
      ["Batteries", 2],
      ["Agents", 1],
      ["Chips", 1],
    ]);
  });
});
