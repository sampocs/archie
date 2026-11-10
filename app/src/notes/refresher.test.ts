import { noteSource } from "@/library/testRows";

import { cardsAddedMessage, DAILY_NOTES, isRefreshable, noteMeta, refresherQueue, todayRefresher } from "./refresher";

const NOW = new Date(2026, 10, 8, 10, 0); // Sun Nov 8, local
const local = (day: number, hour: number, minute = 0): string => new Date(2026, 10, day, hour, minute).toISOString();
const titles = (queue: { title: string | null }[]): (string | null)[] => queue.map((note) => note.title);

describe("isRefreshable", () => {
  it.each([
    ["a live note with a write-up", {}, true],
    ["cards off", { cardsOff: 1 }, false],
    ["already refreshed", { refreshedAt: "2026-11-01T00:00:00Z" }, false],
    ["deleted", { deletedAt: "2026-11-01T00:00:00Z" }, false],
    ["no write-up", { summary: null }, false],
    ["not a note", { kind: "article" }, false],
  ])("%s", (_name, overrides, expected) => {
    expect(isRefreshable(noteSource(overrides))).toBe(expected);
  });
});

describe("refresherQueue", () => {
  it("keeps topic runs together, runs ordered by their newest note", () => {
    const queue = refresherQueue([
      noteSource({ id: "a", title: "A", topicId: "t1", noteEditedAt: "2026-01-10T00:00:00Z" }),
      noteSource({ id: "b", title: "B", topicId: "t2", noteEditedAt: "2026-01-20T00:00:00Z" }),
      noteSource({ id: "c", title: "C", topicId: "t1", noteEditedAt: "2026-01-05T00:00:00Z" }),
      noteSource({ id: "d", title: "D", topicId: "t2", noteEditedAt: "2026-01-01T00:00:00Z" }),
    ]);

    expect(titles(queue)).toEqual(["B", "D", "A", "C"]);
  });

  it("groups topic-less notes by domain, and those without one into a single run", () => {
    const queue = refresherQueue([
      noteSource({ id: "a", title: "A", domain: "AI", noteEditedAt: "2026-01-10T00:00:00Z" }),
      noteSource({ id: "b", title: "B", domain: "Macro", noteEditedAt: "2026-01-09T00:00:00Z" }),
      noteSource({ id: "c", title: "C", domain: "AI", noteEditedAt: "2026-01-08T00:00:00Z" }),
      noteSource({ id: "d", title: "D", noteEditedAt: "2026-01-07T00:00:00Z" }),
      noteSource({ id: "e", title: "E", noteEditedAt: "2026-01-06T00:00:00Z" }),
    ]);

    expect(titles(queue)).toEqual(["A", "C", "B", "D", "E"]);
  });

  it("falls back to createdAt for an unedited note, and breaks ties by id", () => {
    const queue = refresherQueue([
      noteSource({ id: "b", title: "B", noteEditedAt: "2026-01-10T00:00:00Z" }),
      noteSource({ id: "a", title: "A", noteEditedAt: "2026-01-10T00:00:00Z" }),
      noteSource({ id: "c", title: "C", noteEditedAt: null, createdAt: "2026-02-01T00:00:00Z" }),
    ]);

    expect(titles(queue)).toEqual(["C", "A", "B"]);
  });

  it("leaves out notes that are not refreshable", () => {
    const queue = refresherQueue([
      noteSource({ id: "ok", title: "ok" }),
      noteSource({ id: "off", cardsOff: 1 }),
      noteSource({ id: "done", refreshedAt: "2026-11-01T00:00:00Z" }),
      noteSource({ id: "gone", deletedAt: "2026-11-01T00:00:00Z" }),
      noteSource({ id: "bare", summary: null }),
      noteSource({ id: "link", kind: "article" }),
    ]);

    expect(titles(queue)).toEqual(["ok"]);
  });

  it("puts skipped notes last, oldest skip first, without pulling their run back", () => {
    const queue = refresherQueue([
      noteSource({ id: "a", title: "A", topicId: "t1", noteEditedAt: "2026-01-10T00:00:00Z" }),
      noteSource({ id: "s2", title: "S2", topicId: "t2", refreshSkippedAt: "2026-11-07T00:00:00Z" }),
      noteSource({ id: "s1", title: "S1", topicId: "t1", refreshSkippedAt: "2026-11-06T00:00:00Z" }),
      noteSource({ id: "b", title: "B", topicId: "t2", noteEditedAt: "2026-01-02T00:00:00Z" }),
    ]);

    expect(titles(queue)).toEqual(["A", "B", "S1", "S2"]);
  });
});

describe("todayRefresher", () => {
  const queued = [
    noteSource({ id: "q1", title: "Q1", noteEditedAt: "2026-01-04T00:00:00Z" }),
    noteSource({ id: "q2", title: "Q2", noteEditedAt: "2026-01-03T00:00:00Z" }),
    noteSource({ id: "q3", title: "Q3", noteEditedAt: "2026-01-02T00:00:00Z" }),
    noteSource({ id: "q4", title: "Q4", noteEditedAt: "2026-01-01T00:00:00Z" }),
  ];
  const countedToday = (id: string, at = local(8, 8)) =>
    noteSource({ id, title: id, refreshedAt: at, refreshedFromQueue: 1 });

  it("offers the first note as 1 of 2, with the next two titles", () => {
    const result = todayRefresher(queued, NOW);

    expect(DAILY_NOTES).toBe(2);
    expect(result).toMatchObject({ kind: "pick", position: 1, nextUp: ["Q2", "Q3"] });
    expect(result?.kind === "pick" && result.note.id).toBe("q1");
  });

  it("is position 2 after one counted refresh today", () => {
    const result = todayRefresher([...queued, countedToday("done1")], NOW);

    expect(result).toMatchObject({ kind: "pick", position: 2 });
  });

  it("does not count an early refresh from Library", () => {
    const early = noteSource({ id: "early", refreshedAt: local(8, 8), refreshedFromQueue: 0 });
    const result = todayRefresher([...queued, early], NOW);

    expect(result).toMatchObject({ kind: "pick", position: 1 });
    expect(refresherQueue([...queued, early]).map((note) => note.id)).not.toContain("early");
  });

  it("is done for the day after two counted refreshes, naming the next note", () => {
    const result = todayRefresher([...queued, countedToday("d1"), countedToday("d2")], NOW);

    expect(result).toMatchObject({ kind: "done", refreshed: 2 });
    expect(result?.kind === "done" && result.next?.id).toBe("q1");
  });

  it("does not count a refresh from just before midnight yesterday", () => {
    const justAfterMidnight = new Date(2026, 10, 8, 0, 30);
    const yesterday = [countedToday("d1", local(7, 23, 30)), countedToday("d2", local(7, 23, 59))];

    expect(todayRefresher([...queued, ...yesterday], justAfterMidnight)).toMatchObject({ kind: "pick", position: 1 });
  });

  it("counts a refresh just after midnight today", () => {
    const result = todayRefresher([...queued, countedToday("d1", local(8, 0, 1))], new Date(2026, 10, 8, 0, 30));

    expect(result).toMatchObject({ kind: "pick", position: 2 });
  });

  it("shows no card when nothing is queued and nothing was counted", () => {
    expect(todayRefresher([], NOW)).toBeNull();
  });

  it("is done with nothing to name when the queue empties after a counted refresh", () => {
    expect(todayRefresher([countedToday("d1")], NOW)).toEqual({ kind: "done", refreshed: 1, next: null });
  });

  it("has fewer next-up titles when the queue is short", () => {
    expect(todayRefresher(queued.slice(0, 2), NOW)).toMatchObject({ kind: "pick", nextUp: ["Q2"] });
  });

  it("reads the write-up's words (gist, ideas, numbers) as minutes", () => {
    const words = (count: number): string => Array.from({ length: count }, () => "w").join(" ");
    const note = noteSource({
      id: "long",
      summary: {
        gist: words(200),
        key_ideas: [{ idea: words(200), timestamp: null }],
        numbers: [{ fact: words(50), timestamp: null }],
      },
    });
    const result = todayRefresher([note], NOW);

    // 450 words at 220 a minute rounds up to 3; 440 would be 2, so the numbers count.
    expect(result?.kind === "pick" && result.minutes).toBe(3);
  });
});

describe("noteMeta", () => {
  const queue = [1, 2, 3, 4].map((index) => noteSource({ id: `q${index}`, title: `Q${index}` }));

  it("says refreshed today with the card count", () => {
    const note = noteSource({ refreshedAt: local(8, 7), cardCount: 5 });

    expect(noteMeta(note, queue, NOW)).toBe("Notes · refreshed today · 5 cards");
  });

  it("uses a weekday for a refresh three days ago, and no count without cards", () => {
    const note = noteSource({ refreshedAt: local(5, 9), cardCount: 0 });

    expect(noteMeta(note, queue, NOW)).toBe("Notes · refreshed Thu");
  });

  it("uses the singular for one card", () => {
    expect(noteMeta(noteSource({ refreshedAt: local(8, 7), cardCount: 1 }), queue, NOW)).toBe(
      "Notes · refreshed today · 1 card",
    );
  });

  it("uses the date for an older refresh", () => {
    const note = noteSource({ refreshedAt: local(1, 9), cardCount: 2 });

    expect(noteMeta(note, queue, NOW)).toBe("Notes · refreshed Nov 1 · 2 cards");
  });

  it("marks the first in the queue as up next and the rest as to refresh", () => {
    expect(noteMeta(queue[0], queue, NOW)).toBe("Notes · up next");
    expect(noteMeta(queue[3], queue, NOW)).toBe("Notes · to refresh");
  });

  it("says from Bear for a note without a write-up, and plain Notes with cards off", () => {
    expect(noteMeta(noteSource({ summary: null }), queue, NOW)).toBe("Notes · from Bear");
    expect(noteMeta(noteSource({ cardsOff: 1 }), queue, NOW)).toBe("Notes");
  });
});

describe("cardsAddedMessage", () => {
  it("pluralizes", () => {
    expect(cardsAddedMessage(1, "X")).toBe("1 review card added from X");
    expect(cardsAddedMessage(5, "X")).toBe("5 review cards added from X");
  });
});
