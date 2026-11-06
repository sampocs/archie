import { applyGrade, knewItState } from "./schedule";
import {
  appendTranscript,
  doneSummaryLine,
  elapsedMinutes,
  gradeWithin,
  isOffline,
  knewItInput,
  nextLiveIndex,
  OFFLINE_REASON,
  parseVerdict,
  recordedReview,
  reviewInputFor,
  sessionModeOf,
  submitRoute,
  uploadDurationMs,
} from "./sessionFlow";
import { dayAt, NOW, reviewCard } from "./testCards";
import { fsrsFieldsOf } from "./types";

describe("submitRoute", () => {
  const online = { isConnected: true, isInternetReachable: true };

  it("an empty box self-grades with no reason, even offline", () => {
    expect(submitRoute("  ", online)).toEqual({ kind: "self", reason: null });
    expect(submitRoute("", { isConnected: false })).toEqual({ kind: "self", reason: null });
  });

  it("offline (not connected, or the internet unreachable) self-grades with the offline reason", () => {
    expect(submitRoute("inflation", { isConnected: false, isInternetReachable: null })).toEqual({
      kind: "self",
      reason: OFFLINE_REASON,
    });
    expect(submitRoute("inflation", { isConnected: true, isInternetReachable: false })).toEqual({
      kind: "self",
      reason: OFFLINE_REASON,
    });
  });

  it("online goes to the grader; an unknown reachability counts as online", () => {
    expect(submitRoute("inflation", online)).toEqual({ kind: "grade" });
    expect(submitRoute("inflation", { isConnected: true, isInternetReachable: null })).toEqual({ kind: "grade" });
    expect(isOffline({})).toBe(false);
  });
});

describe("parseVerdict", () => {
  it("accepts a grade and a missing line", () => {
    const body = { grade: "partly", missing: "the spiral" };
    expect(parseVerdict(body)).toEqual(body);
  });

  it("rejects anything else", () => {
    expect(parseVerdict(null)).toBeNull();
    expect(parseVerdict("got_it")).toBeNull();
    expect(parseVerdict({ grade: "great", missing: "" })).toBeNull();
    expect(parseVerdict({ grade: "got_it" })).toBeNull();
  });
});

describe("gradeWithin", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("returns the verdict that arrives in time", async () => {
    const verdict = gradeWithin(async () => ({ grade: "got_it", missing: "" }), 3000);
    await expect(verdict).resolves.toEqual({ grade: "got_it", missing: "" });
  });

  it("times out: aborts the call and ignores a response that lands later", async () => {
    let signal: AbortSignal | undefined;
    let respond: (body: unknown) => void = () => {};
    const verdict = gradeWithin((given) => {
      signal = given;
      return new Promise((resolve) => (respond = resolve));
    }, 3000);

    jest.advanceTimersByTime(3000);
    respond({ grade: "got_it", missing: "" });
    await expect(verdict).resolves.toBeNull();
    expect(signal?.aborted).toBe(true);
  });

  it("a failed call or a malformed body is null", async () => {
    await expect(gradeWithin(() => Promise.reject(new Error("502")), 3000)).resolves.toBeNull();
    await expect(gradeWithin(async () => ({ detail: "nope" }), 3000)).resolves.toBeNull();
  });
});

describe("reviewInputFor and knewItInput", () => {
  const card = reviewCard({ id: "c1", dueAt: dayAt(-1) });

  it("a model grade keeps the missing line for partly and missed, and schedules from the card's state", () => {
    const input = reviewInputFor(card, {
      grade: "partly",
      gradedBy: "model",
      answer: " inflation ",
      missing: "the spiral",
      wasDue: true,
      now: NOW,
    });
    expect(input).toEqual({
      cardId: "c1",
      grade: "partly",
      gradedBy: "model",
      answer: "inflation",
      missing: "the spiral",
      wasDue: true,
      reviewedAt: NOW,
      stateBefore: fsrsFieldsOf(card),
      stateAfter: applyGrade({ ...fsrsFieldsOf(card), kind: card.kind }, "partly", NOW, true),
    });
  });

  it("drops the missing line for got_it and for any self-grade; an empty answer is null", () => {
    const base = { answer: "x", missing: "", wasDue: true, now: NOW };
    expect(reviewInputFor(card, { ...base, grade: "got_it", gradedBy: "model" }).missing).toBeNull();
    expect(reviewInputFor(card, { ...base, grade: "missed", gradedBy: "self", missing: "y" }).missing).toBeNull();
    expect(reviewInputFor(card, { ...base, answer: " ", grade: "missed", gradedBy: "self" }).answer).toBeNull();
  });

  it("I actually knew it replaces the review, starting from that review's state", () => {
    const first = reviewInputFor(card, {
      grade: "missed",
      gradedBy: "model",
      answer: "no idea",
      missing: "all of it",
      wasDue: false,
      now: NOW,
    });
    const replaced = recordedReview("r1", first);
    const later = new Date(NOW.getTime() + 5_000);
    // The card row now holds the missed state; the redo must ignore it.
    const graded = { ...card, ...first.stateAfter };

    expect(knewItInput(graded, replaced, "no idea", later)).toEqual({
      cardId: "c1",
      grade: "got_it",
      gradedBy: "self",
      answer: "no idea",
      missing: null,
      wasDue: false,
      reviewedAt: later,
      stateBefore: fsrsFieldsOf(card),
      stateAfter: knewItState(card.kind, replaced),
      replacesReviewId: "r1",
    });
    expect(replaced.reviewedAt).toBe(NOW.toISOString());
  });
});

describe("nextLiveIndex", () => {
  const ids = ["a", "b", "c"];

  it("skips cards that were deleted meanwhile", () => {
    expect(nextLiveIndex(ids, 0, () => true)).toBe(0);
    expect(nextLiveIndex(ids, 1, (id) => id !== "b")).toBe(2);
    expect(nextLiveIndex(ids, 1, (id) => id === "a")).toBe(3);
    expect(nextLiveIndex(ids, 3, () => true)).toBe(3);
  });
});

describe("small helpers", () => {
  it("sessionModeOf falls back to due", () => {
    expect(sessionModeOf("ahead")).toBe("ahead");
    expect(sessionModeOf("card")).toBe("card");
    expect(sessionModeOf("bogus")).toBe("due");
    expect(sessionModeOf(undefined)).toBe("due");
  });

  it("appendTranscript adds after a space, or fills an empty box", () => {
    expect(appendTranscript("", " it spirals ")).toBe("it spirals");
    expect(appendTranscript("inflation ", "it spirals")).toBe("inflation it spirals");
    expect(appendTranscript("inflation", "  ")).toBe("inflation");
  });

  it("uploadDurationMs stays within 1 ms to 125 s", () => {
    expect(uploadDurationMs(0)).toBe(1);
    expect(uploadDurationMs(4321.6)).toBe(4322);
    expect(uploadDurationMs(130_000)).toBe(125_000);
  });

  it("elapsedMinutes rounds up, at least 1", () => {
    expect(elapsedMinutes(NOW, NOW)).toBe(1);
    expect(elapsedMinutes(NOW, new Date(NOW.getTime() + 61_000))).toBe(2);
  });
});

describe("doneSummaryLine", () => {
  it("says how many and how long, then when the next review is", () => {
    expect(doneSummaryLine(1, 1, null, NOW)).toBe("1 card in 1 minute.");
    expect(doneSummaryLine(8, 4, { at: new Date(dayAt(1)), count: 5 }, NOW)).toBe(
      "8 cards in 4 minutes. Next review tomorrow: 5 cards.",
    );
  });
});
