import { DEFAULT_REVIEW_SETTINGS } from "@/db/reviewSettings";

import { reminderPlan } from "./reminder";
import { cardRow, dayAt, NOW, reviewCard, reviewData, reviewRow } from "./testCards";

const evening = (days: number): Date => new Date(dayAt(days, 20, 30));

describe("reminderPlan", () => {
  it("plans nothing when reminders are off", () => {
    const settings = { ...DEFAULT_REVIEW_SETTINGS, reminderEnabled: false };
    expect(reminderPlan(reviewData([cardRow({})]), settings, NOW)).toEqual([]);
  });

  it("reminds only from the day a card comes due, through the next 7 days", () => {
    const plan = reminderPlan(reviewData([reviewCard({ dueAt: dayAt(2, 9) })]), DEFAULT_REVIEW_SETTINGS, NOW);

    expect(plan.map(({ at }) => at)).toEqual([2, 3, 4, 5, 6].map(evening));
    expect(plan[0]).toEqual({ at: evening(2), count: 1, body: "1 card · about 1 min" });
  });

  it("skips today once today's reminder time has passed, and uses the chosen time", () => {
    const settings = { reminderEnabled: true, reminderMinutes: 7 * 60 + 15, dailyLimit: null };
    const plan = reminderPlan(reviewData([cardRow({})]), settings, NOW);

    expect(plan.map(({ at }) => at)).toEqual([1, 2, 3, 4, 5, 6].map((days) => new Date(dayAt(days, 7, 15))));
  });

  it("counts a card that starts later only in the reminders from its start on", () => {
    const plan = reminderPlan(reviewData([cardRow({ availableAt: dayAt(2, 9) })]), DEFAULT_REVIEW_SETTINGS, NOW);

    expect(plan.map(({ at }) => at)).toEqual([2, 3, 4, 5, 6].map(evening));
  });

  it("counts every card due by then and leaves out unreviewable ones", () => {
    const cards = [
      ...Array.from({ length: 11 }, (_, index) => cardRow({ id: `new-${index}` })),
      reviewCard({ id: "tomorrow", dueAt: dayAt(1, 8) }),
      cardRow({ id: "unreviewable", sourceId: "s9" }),
    ];
    const plan = reminderPlan(reviewData(cards), DEFAULT_REVIEW_SETTINGS, NOW);

    expect(plan.slice(0, 2).map(({ count, body }) => [count, body])).toEqual([
      [11, "11 cards · about 4 min"],
      [12, "12 cards · about 4 min"],
    ]);
  });

  it("caps each day's count at the daily limit, and today's at what is left of it", () => {
    const due = Array.from({ length: 30 }, (_, index) => cardRow({ id: `new-${index}` }));
    const reviewed = ["r1", "r2", "r3"].map((id) => reviewCard({ id, dueAt: dayAt(5) }));
    const reviews = reviewed.map(({ id }) => reviewRow({ id: `review-${id}`, cardId: id, reviewedAt: dayAt(0, 9) }));
    const settings = { ...DEFAULT_REVIEW_SETTINGS, dailyLimit: 10 };
    const plan = reminderPlan(reviewData([...due, ...reviewed], { reviews }), settings, NOW);

    expect(plan.slice(0, 2).map(({ at, count }) => [at, count])).toEqual([
      [evening(0), 7],
      [evening(1), 10],
    ]);
  });

  it("drops today's reminder once today's cap is reviewed", () => {
    const reviewed = Array.from({ length: 10 }, (_, index) => reviewCard({ id: `r${index}`, dueAt: dayAt(5) }));
    const reviews = reviewed.map(({ id }) => reviewRow({ id: `review-${id}`, cardId: id, reviewedAt: dayAt(0, 9) }));
    const data = reviewData([cardRow({ id: "left" }), ...reviewed], { reviews });
    const plan = reminderPlan(data, { ...DEFAULT_REVIEW_SETTINGS, dailyLimit: 10 }, NOW);

    expect(plan[0].at).toEqual(evening(1));
  });
});
