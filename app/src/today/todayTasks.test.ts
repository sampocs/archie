import type { BriefContent, BriefRow } from "@/brief/brief";
import { noteSource, sourceRow } from "@/library/testRows";
import type { LibrarySource } from "@/library/join";
import { cardRow, dayAt, NOW, reviewCard, reviewData } from "@/review/testCards";
import type { CardRow, ReviewRow } from "@/review/types";

import {
  backTomorrow,
  dayDoneChips,
  doneTaskKinds,
  joinNaturally,
  todayTasks,
  type TodayInputs,
} from "./todayTasks";

// NOW is Thursday Nov 5 2026, noon (America/New_York, pinned by jest.config.js).
const review = (overrides: Partial<ReviewRow>): ReviewRow => ({
  id: `r-${overrides.cardId ?? "c1"}-${overrides.reviewedAt ?? ""}`,
  cardId: "c1",
  grade: "got_it",
  gradedBy: "model",
  answer: null,
  missing: null,
  wasDue: 1,
  reviewedAt: dayAt(0, 9),
  stateBefore: "{}",
  stateAfter: "{}",
  replacesReviewId: null,
  ...overrides,
});

const briefContent = (stories: number): string => {
  const content: BriefContent = {
    domains: [
      {
        domain: "AI",
        stories: Array.from({ length: stories }, (_, index) => ({
          headline: `H${index}`, body: "", why: "", detail: "", importance: 5, source_ids: [],
        })),
      },
    ],
    also: [],
    essays: [],
  };
  return JSON.stringify(content);
};

const brief = (overrides: Partial<BriefRow>): BriefRow => ({
  id: "b1", status: "open", content: briefContent(3), sourceIds: "[]", since: null, version: 1,
  createdAt: dayAt(0, 6), updatedAt: dayAt(0, 6), doneAt: null,
  ...overrides,
});

// A card already reviewed and scheduled `days` out, so it is not due now.
const scheduled = (id: string, days: number, hour = 12): CardRow => reviewCard({ id, dueAt: dayAt(days, hour) });
const dueCard = (id: string): CardRow => reviewCard({ id, dueAt: dayAt(-1) });
const quizCard = (overrides: Partial<CardRow>): CardRow =>
  cardRow({ sourceId: null, briefId: "b0", kind: "quiz", expiresAt: dayAt(2), ...overrides });

function inputs(overrides: Partial<Omit<TodayInputs, "reviewData">> & { cards?: CardRow[] } = {}): TodayInputs {
  const { cards = [], reviews = [], ...rest } = overrides;
  return {
    reviewData: reviewData(cards, { reviews }),
    reviews,
    sources: [],
    briefs: [],
    dailyLimit: null,
    now: NOW,
    ...rest,
  };
}

describe("review task", () => {
  it("is absent with nothing due and nothing reviewed today", () => {
    expect(todayTasks(inputs({ cards: [scheduled("later", 2)] })).review).toBeNull();
  });

  it("waits with the due count and minutes before any review today", () => {
    const cards = [dueCard("a"), dueCard("b"), dueCard("c"), dueCard("d")];

    expect(todayTasks(inputs({ cards })).review).toEqual({ status: "pending", due: 4, minutes: 2, waiting: 0 });
  });

  it("is under way with today's set as reviewed plus still due", () => {
    const cards = [dueCard("left1"), dueCard("left2"), scheduled("r1", 3), scheduled("r2", 3), scheduled("r3", 3)];
    const reviews = ["r1", "r2", "r3"].map((cardId) => review({ cardId }));

    expect(todayTasks(inputs({ cards, reviews })).review).toEqual({
      status: "inProgress", due: 2, minutes: 1, reviewed: 3, total: 5,
    });
  });

  it("counts a card reviewed twice today once", () => {
    const cards = [dueCard("left"), scheduled("r1", 3)];
    const reviews = [review({ cardId: "r1", reviewedAt: dayAt(0, 9) }), review({ cardId: "r1", reviewedAt: dayAt(0, 10) })];

    expect(todayTasks(inputs({ cards, reviews })).review).toMatchObject({ reviewed: 1, total: 2 });
  });

  it("leaves out reviews of cards that weren't due (ahead) and quiz answers", () => {
    const cards = [dueCard("left"), scheduled("ahead", 3), quizCard({ id: "q1", lastReviewAt: dayAt(0, 9) })];
    const reviews = [review({ cardId: "ahead", wasDue: 0 }), review({ cardId: "q1" })];

    expect(todayTasks(inputs({ cards, reviews })).review).toEqual({
      status: "pending", due: 1, minutes: 1, waiting: 0,
    });
  });

  it("counts only reviews since local midnight", () => {
    const justAfterMidnight = new Date(2026, 10, 5, 0, 30);
    const cards = [dueCard("left"), scheduled("yesterday", 3), scheduled("today", 3)];
    const reviews = [
      review({ cardId: "yesterday", reviewedAt: dayAt(-1, 23, 59) }),
      review({ cardId: "today", reviewedAt: dayAt(0, 0, 1) }),
    ];

    expect(todayTasks(inputs({ cards, reviews, now: justAfterMidnight })).review).toMatchObject({
      status: "inProgress", reviewed: 1, total: 2,
    });
  });

  it("is done when nothing is left, naming when the next cards come due", () => {
    const cards = [scheduled("r1", 1, 9), scheduled("r2", 1, 18), scheduled("later", 4)];
    const reviews = [review({ cardId: "r1" }), review({ cardId: "r2" })];

    expect(todayTasks(inputs({ cards, reviews })).review).toEqual({
      status: "done", reviewed: 2, next: "2 tomorrow", waiting: 0,
    });
  });

  it.each([
    ["later today", dayAt(0, 18), "1 later today"],
    ["within a week, by weekday", dayAt(3), "1 on Sun"],
    ["further out, by date", dayAt(9), "1 on Nov 14"],
  ])("names the next review %s", (_name, dueAt, next) => {
    const cards = [reviewCard({ id: "r1", dueAt })];

    expect(todayTasks(inputs({ cards, reviews: [review({ cardId: "r1" })] })).review).toMatchObject({ next });
  });

  it("is done with no next when no card waits", () => {
    const reviews = [review({ cardId: "gone" })];

    expect(todayTasks(inputs({ reviews })).review).toEqual({ status: "done", reviewed: 1, next: null, waiting: 0 });
  });

  describe("with a daily cap", () => {
    const manyDue = (count: number): CardRow[] => Array.from({ length: count }, (_, index) => dueCard(`d${index}`));

    it("waits with only the capped set, naming the cards held back", () => {
      expect(todayTasks(inputs({ cards: manyDue(34), dailyLimit: 20 })).review).toEqual({
        status: "pending", due: 20, minutes: 7, waiting: 14,
      });
    });

    it("is under way against what is left of the cap", () => {
      const cards = [...manyDue(30), ...["r1", "r2", "r3"].map((id) => scheduled(id, 3))];
      const reviews = ["r1", "r2", "r3"].map((cardId) => review({ cardId }));

      expect(todayTasks(inputs({ cards, reviews, dailyLimit: 10 })).review).toMatchObject({
        status: "inProgress", due: 7, reviewed: 3, total: 10,
      });
    });

    it("is done once the cap is reviewed, with the rest waiting", () => {
      const reviewedIds = Array.from({ length: 10 }, (_, index) => `r${index}`);
      const cards = [...manyDue(4), ...reviewedIds.map((id) => scheduled(id, 3))];
      const reviews = reviewedIds.map((cardId) => review({ cardId }));
      const tasks = todayTasks(inputs({ cards, reviews, dailyLimit: 10 }));

      expect(tasks.review).toMatchObject({ status: "done", reviewed: 10, waiting: 4 });
      expect(tasks.dayDone).toBe(true);
    });
  });
});

describe("notes task", () => {
  const counted = (id: string, at = dayAt(0, 8)): LibrarySource =>
    noteSource({ id, title: id, refreshedAt: at, refreshedFromQueue: 1 });
  const queued = [noteSource({ id: "q1", title: "Q1" }), noteSource({ id: "q2", title: "Q2" })];

  it("is absent with no notes to refresh and none refreshed today", () => {
    expect(todayTasks(inputs({ sources: [counted("old", dayAt(-1, 8))] })).notes).toBeNull();
  });

  it("waits on the first note, and is under way on the second", () => {
    expect(todayTasks(inputs({ sources: queued })).notes?.status).toBe("pending");
    expect(todayTasks(inputs({ sources: [...queued, counted("d1")] })).notes?.status).toBe("inProgress");
  });

  it("is done after today's notes, with how many and the next note", () => {
    const notes = todayTasks(inputs({ sources: [...queued, counted("d1"), counted("d2")] })).notes;

    expect(notes).toMatchObject({ status: "done", refreshed: 2 });
    expect(notes?.status === "done" && notes.next?.id).toBe("q1");
  });
});

describe("quiz task", () => {
  it("waits while the week's quiz is open", () => {
    const cards = [quizCard({ id: "q1" }), quizCard({ id: "q2", lastReviewAt: dayAt(0, 9) })];

    expect(todayTasks(inputs({ cards })).quiz).toEqual({ status: "pending", count: 1, until: new Date(dayAt(2)) });
  });

  it("is done on the day its last answer came, counting the latest grade of each answer", () => {
    const cards = [
      quizCard({ id: "q1", lastReviewAt: dayAt(-1, 9) }),
      quizCard({ id: "q2", lastReviewAt: dayAt(0, 9) }),
      quizCard({ id: "q3", lastReviewAt: dayAt(0, 10) }),
      // Last week's quiz has its own expiry and stays out.
      quizCard({ id: "old", expiresAt: dayAt(-5), lastReviewAt: dayAt(-6) }),
    ];
    const reviews = [
      review({ cardId: "q1", reviewedAt: dayAt(-1, 9), grade: "got_it" }),
      review({ cardId: "q2", reviewedAt: dayAt(0, 9), grade: "missed" }),
      // "I actually knew it" replaces the missed grade.
      review({ cardId: "q2", reviewedAt: dayAt(0, 9, 1), grade: "got_it" }),
      review({ cardId: "q3", reviewedAt: dayAt(0, 10), grade: "partly" }),
    ];

    expect(todayTasks(inputs({ cards, reviews })).quiz).toEqual({ status: "done", gotIt: 2, answered: 3 });
  });

  it("is absent the day after it was finished", () => {
    const cards = [quizCard({ id: "q1", lastReviewAt: dayAt(-1, 9) })];

    expect(todayTasks(inputs({ cards })).quiz).toBeNull();
  });

  it("is absent with no quiz", () => {
    expect(todayTasks(inputs()).quiz).toBeNull();
  });
});

describe("brief task", () => {
  it("waits on the open brief", () => {
    expect(todayTasks(inputs({ briefs: [brief({})] })).brief?.status).toBe("pending");
  });

  it("waits while a brief is being written", () => {
    const sources = [sourceRow({ kind: "newsletter", state: "inbox", processing: "ready" })];

    expect(todayTasks(inputs({ sources })).brief).toMatchObject({
      status: "pending", brief: { kind: "writing", newsletters: 1 },
    });
  });

  it("is done with the story count once today's brief is finished", () => {
    const briefs = [
      brief({ id: "earlier", status: "done", content: briefContent(2), doneAt: dayAt(-1, 8) }),
      brief({ id: "today", status: "done", content: briefContent(6), doneAt: dayAt(0, 8) }),
    ];

    expect(todayTasks(inputs({ briefs })).brief).toEqual({ status: "done", stories: 6 });
  });

  it("waits again when a new brief opens after one was finished today", () => {
    const briefs = [brief({ id: "read", status: "done", doneAt: dayAt(0, 8) }), brief({ id: "new" })];

    expect(todayTasks(inputs({ briefs })).brief?.status).toBe("pending");
  });

  it("is absent when the last brief was finished yesterday", () => {
    const briefs = [brief({ status: "done", doneAt: dayAt(-1, 23, 59) })];

    expect(todayTasks(inputs({ briefs })).brief).toBeNull();
  });
});

describe("day done", () => {
  const doneBrief = [brief({ status: "done", doneAt: dayAt(0, 8) })];

  it("is done when every task shown today is done, ignoring tasks absent today", () => {
    const tasks = todayTasks(inputs({ briefs: doneBrief, cards: [scheduled("r1", 1)], reviews: [review({ cardId: "r1" })] }));

    expect(tasks.dayDone).toBe(true);
    expect(doneTaskKinds(tasks)).toEqual(["review", "brief"]);
  });

  it("is not done while any task waits or is under way", () => {
    const cards = [dueCard("left"), scheduled("r1", 1)];

    expect(todayTasks(inputs({ briefs: doneBrief, cards, reviews: [review({ cardId: "r1" })] })).dayDone).toBe(false);
    expect(todayTasks(inputs({ briefs: [brief({})] })).dayDone).toBe(false);
  });

  it("is not done when nothing was on today", () => {
    expect(todayTasks(inputs()).dayDone).toBe(false);
  });

  it("ticks a chip per finished task, in Today's order", () => {
    const sources = [
      noteSource({ id: "d1", refreshedAt: dayAt(0, 8), refreshedFromQueue: 1 }),
      noteSource({ id: "d2", refreshedAt: dayAt(0, 9), refreshedFromQueue: 1 }),
    ];
    const cards = [scheduled("r1", 1), quizCard({ id: "q1", lastReviewAt: dayAt(0, 9) })];
    const tasks = todayTasks(inputs({ briefs: doneBrief, sources, cards, reviews: [review({ cardId: "r1" })] }));

    expect(dayDoneChips(tasks)).toEqual(["1 card", "2 notes", "Quiz", "Brief"]);
  });
});

describe("backTomorrow", () => {
  it("names cards due by the end of tomorrow, tomorrow's notes and a new brief", () => {
    const cards = [scheduled("r1", 1, 23), scheduled("r2", 1, 8), scheduled("dayAfter", 2, 0)];
    const sources = [noteSource({ id: "q1" }), noteSource({ id: "q2" }), noteSource({ id: "q3" })];
    const briefs = [brief({ status: "done", doneAt: dayAt(0, 8) })];
    const today = inputs({ cards, sources, briefs, reviews: [review({ cardId: "r1" })] });

    expect(backTomorrow(today, todayTasks(today))).toBe("Back tomorrow: 2 cards, 2 notes and a new brief.");
  });

  it("names one note when only one is queued, and no brief when none was read today", () => {
    const today = inputs({ sources: [noteSource({ id: "q1" })] });

    expect(backTomorrow(today, todayTasks(today))).toBe("Back tomorrow: 1 note.");
  });

  it("counts today's held-back cards with tomorrow's, up to the cap", () => {
    const reviewedIds = Array.from({ length: 10 }, (_, index) => `r${index}`);
    const held = Array.from({ length: 6 }, (_, index) => dueCard(`held${index}`));
    const tomorrow = Array.from({ length: 6 }, (_, index) => scheduled(`t${index}`, 1, 9));
    const cards = [...held, ...tomorrow, ...reviewedIds.map((id) => scheduled(id, 5))];
    const reviews = reviewedIds.map((cardId) => review({ cardId }));

    const capped = inputs({ cards, reviews, dailyLimit: 10 });
    expect(backTomorrow(capped, todayTasks(capped))).toBe("Back tomorrow: 10 cards.");
    const few = inputs({ cards: cards.slice(4), reviews, dailyLimit: 10 });
    expect(backTomorrow(few, todayTasks(few))).toBe("Back tomorrow: 8 cards.");
  });

  it("says just that when tomorrow holds nothing known", () => {
    const today = inputs({ cards: [scheduled("far", 5)] });

    expect(backTomorrow(today, todayTasks(today))).toBe("Back tomorrow.");
  });
});

describe("joinNaturally", () => {
  it.each([
    [[], ""],
    [["a"], "a"],
    [["a", "b"], "a and b"],
    [["a", "b", "c"], "a, b and c"],
  ])("%p → %p", (parts, joined) => {
    expect(joinNaturally(parts)).toBe(joined);
  });
});
