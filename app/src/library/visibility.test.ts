import type { LibrarySource } from "./join";
import { sourceRow } from "./testRows";
import { isSnoozed, queueOrder, statusTag, upNext } from "./visibility";

const NOW = new Date("2026-11-04T15:00:00Z");
const PAST = "2026-11-04T14:00:00Z";
const FUTURE = "2026-11-05T14:00:00Z";

const source = sourceRow;

describe("statusTag", () => {
  it.each([
    [{ state: "queued", processing: "pending", readAt: null }, "Processing"],
    [{ state: "consumed", processing: "processing", readAt: null }, "Processing"],
    [{ state: "queued", processing: "failed", readAt: null }, "Failed"],
    [{ state: "queued", processing: "ready", readAt: null }, "Queued"],
    [{ state: "consumed", processing: "ready", readAt: null }, "Done"],
    [{ state: "briefed", processing: "ready", readAt: null }, "Briefed"],
    [{ state: "inbox", processing: "ready", readAt: null }, "Unread"],
    [{ state: "inbox", processing: "ready", readAt: PAST }, "Read"],
  ] as const)("%p → %s", (row, expected) => {
    expect(statusTag(row)).toBe(expected);
  });
});

describe("isSnoozed", () => {
  it("is snoozed only until a future time", () => {
    expect(isSnoozed({ snoozedUntil: FUTURE }, NOW)).toBe(true);
    expect(isSnoozed({ snoozedUntil: PAST }, NOW)).toBe(false);
    expect(isSnoozed({ snoozedUntil: null }, NOW)).toBe(false);
  });
});

describe("queueOrder", () => {
  it("orders queued sources and queued primers together by position, unpositioned sources last, newest first", () => {
    const sources = [
      source({ id: "unpositioned-old", state: "queued", createdAt: "2026-11-01T00:00:00Z" }),
      source({ id: "second", state: "queued", queuePosition: 2 }),
      source({ id: "unpositioned-new", state: "queued", createdAt: "2026-11-02T00:00:00Z" }),
      source({ id: "first", state: "queued", queuePosition: -1 }),
      // A finished item whose primer was queued from the finish sheet: only its primer is in the queue.
      source({ id: "lost", state: "consumed", queuePosition: -7, primerQueuePosition: 0.5 }),
      // A queued item with its primer queued above it: two entries.
      source({ id: "both", state: "queued", queuePosition: 3, primerQueuePosition: -3 }),
      source({ id: "inbox", state: "inbox", queuePosition: -9 }),
    ];

    expect(queueOrder(sources).map((entry) => entry.key)).toEqual([
      "primer-both",
      "source-first",
      "primer-lost",
      "source-second",
      "source-both",
      "source-unpositioned-new",
      "source-unpositioned-old",
    ]);
  });
});

describe("upNext", () => {
  it("leaves out snoozed sources and snoozed primers, each by its own snooze time", () => {
    const sources = [
      source({ id: "snoozed", state: "queued", queuePosition: -5, snoozedUntil: FUTURE }),
      // The source is snoozed, its queued primer isn't.
      source({ id: "primer-awake", state: "consumed", primerQueuePosition: -4, snoozedUntil: FUTURE }),
      // The primer is snoozed, its queued source isn't.
      source({
        id: "primer-asleep",
        state: "queued",
        queuePosition: 1,
        primerQueuePosition: -2,
        primerSnoozedUntil: FUTURE,
      }),
      source({ id: "woke", state: "queued", queuePosition: 0, snoozedUntil: PAST }),
    ];

    expect(upNext(sources, NOW).map((entry) => entry.key)).toEqual([
      "primer-primer-awake",
      "source-woke",
      "source-primer-asleep",
    ]);
  });
});
