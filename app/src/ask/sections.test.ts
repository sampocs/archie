import type { AnswerSegment, LibraryCitation, WebCitation } from "./types";
import {
  applyEvent,
  chipText,
  EMPTY_LIVE,
  endOfStream,
  groupSections,
  handedOver,
  liveView,
  relativeTime,
  rowPreview,
} from "./sections";

const library = (overrides: Partial<LibraryCitation> = {}): LibraryCitation => ({
  kind: "library",
  title: "Odd Lots",
  source_id: "s1",
  topic_primer_id: null,
  take_id: null,
  owner_kind: "source_text",
  start_seconds: null,
  quote: null,
  ...overrides,
});
const web: WebCitation = { kind: "web", title: "The Fed", url: "https://www.federalreserve.gov/x", quote: null };

describe("groupSections", () => {
  it("joins consecutive blocks with the same label and drops empty ones", () => {
    const segments: AnswerSegment[] = [
      { label: "library", text: "It buys bonds.", citations: [library({ start_seconds: 1880 })] },
      { label: "library", text: "Reserves sit at the Fed.", citations: [library({ start_seconds: 1880 })] },
      { label: "background", text: "  ", citations: [] },
      { label: "background", text: "Printing is shorthand.", citations: [] },
      { label: "web", text: "About $6.6T.", citations: [web] },
    ];

    expect(groupSections(segments)).toEqual([
      { label: "library", text: "It buys bonds. Reserves sit at the Fed.", citations: [library({ start_seconds: 1880 })] },
      { label: "background", text: "Printing is shorthand.", citations: [] },
      { label: "web", text: "About $6.6T.", citations: [web] },
    ]);
  });
});

describe("chipText", () => {
  it("names the item, with its time, Summary or Primer; a link shows its site", () => {
    expect(chipText(library({ start_seconds: 1880 }))).toBe("Odd Lots · 31:20");
    expect(chipText(library({ owner_kind: "source_summary" }))).toBe("Odd Lots · Summary");
    expect(chipText(library({ owner_kind: "topic_primer", title: "Monetary plumbing" }))).toBe(
      "Monetary plumbing · Primer",
    );
    expect(chipText(library({ owner_kind: "take", title: "My take" }))).toBe("My take");
    expect(chipText(web)).toBe("federalreserve.gov");
  });
});

describe("applyEvent and liveView", () => {
  it("shows streaming text unlabelled until its block ends, then as a labelled section", () => {
    const events = [
      { type: "searching", kind: "library", query: "fed" },
      { type: "delta", block: 0, text: "It buys " },
      { type: "delta", block: 0, text: "bonds." },
    ] as const;
    const streaming = events.reduce(applyEvent, EMPTY_LIVE);

    expect(liveView(streaming)).toEqual({ sections: [], streamingText: "It buys bonds.", searching: null, editing: false });

    const finished = applyEvent(streaming, { type: "block", block: 0, label: "library", citations: [library()] });
    expect(liveView(finished).sections).toEqual([{ label: "library", text: "It buys bonds.", citations: [library()] }]);
    expect(applyEvent(finished, { type: "done", message_id: "m2" }).messageId).toBe("m2");
    expect(applyEvent(finished, { type: "error", message: "x" }).failed).toBe(true);
  });

  it("shows the searching line until text arrives", () => {
    const live = applyEvent(EMPTY_LIVE, { type: "searching", kind: "web", query: "fed funds rate" });
    expect(liveView(live).searching).toBe("web");
  });

  it("an editing event shows the drafting line and an edit event adds its proposal once", () => {
    const wire = {
      id: "p1",
      target_kind: "summary" as const,
      target_id: "s1",
      title: "Index funds",
      description: "Drop the fees idea",
      base_version: 1,
      before: {},
      after: {},
      status: "proposed" as const,
    };
    const drafting = applyEvent(EMPTY_LIVE, { type: "editing", target_kind: null });
    expect(drafting.editing).toBe(true);

    const proposed = applyEvent(applyEvent(drafting, { type: "edit", ...wire }), { type: "edit", ...wire });
    expect(proposed.proposals).toEqual([wire]);
    expect(proposed.editing).toBe(false);
    expect(liveView(proposed).editing).toBe(false);

    const searched = applyEvent(drafting, { type: "searching", kind: "library", query: "x" });
    expect(searched.editing).toBe(false);
    expect(searched.searching).toBe("library");
  });
});

describe("relativeTime and rowPreview", () => {
  const now = new Date(2026, 10, 6, 15, 0);

  it("reads like the mock: minutes, hours, Yesterday, weekday, then a date", () => {
    expect(relativeTime(new Date(2026, 10, 6, 14, 55).toISOString(), now)).toBe("5m");
    expect(relativeTime(new Date(2026, 10, 6, 13, 0).toISOString(), now)).toBe("2h");
    expect(relativeTime(new Date(2026, 10, 5, 9, 0).toISOString(), now)).toBe("Yesterday");
    expect(relativeTime(new Date(2026, 10, 3, 9, 0).toISOString(), now)).toBe("Tue");
    expect(relativeTime(new Date(2026, 9, 2, 9, 0).toISOString(), now)).toBe("Oct 2");
  });

  it("previews the last answer's first line after its label", () => {
    const segments: AnswerSegment[] = [{ label: "background", text: "Apple's buybacks run about $90B.\nMore.", citations: [] }];
    expect(rowPreview(segments)).toBe("Background: Apple's buybacks run about $90B.");
    expect(rowPreview([])).toBe("");
  });
});

describe("endOfStream", () => {
  it("fails an answer whose stream closed without done or error", () => {
    const live = { ...EMPTY_LIVE, searching: "web" as const };
    expect(endOfStream(live)).toEqual({ ...EMPTY_LIVE, failed: true, searching: null });
  });

  it("leaves a finished or failed answer alone", () => {
    const done = { ...EMPTY_LIVE, messageId: "a1" };
    expect(endOfStream(done)).toBe(done);
    const failed = { ...EMPTY_LIVE, failed: true };
    expect(endOfStream(failed)).toBe(failed);
  });
});

describe("handedOver", () => {
  const question = { id: "q1", role: "user" };
  const answer = { id: "a1", role: "assistant" };

  it("is true once the question and the complete answer are pulled", () => {
    const pending = { userMessageId: "q1", live: { ...EMPTY_LIVE, messageId: "a1" } };
    expect(handedOver(pending, [question, answer])).toBe(true);
  });

  it("is false while only the question has been pulled", () => {
    const pending = { userMessageId: "q1", live: { ...EMPTY_LIVE, messageId: "a1" } };
    expect(handedOver(pending, [question])).toBe(false);
  });

  it("is true for a failed stream once a later assistant row exists", () => {
    const pending = { userMessageId: "q1", live: { ...EMPTY_LIVE, failed: true } };
    expect(handedOver(pending, [question, { id: "a9", role: "assistant" }])).toBe(true);
  });

  it("is false for a failed stream with no assistant row after the question", () => {
    const pending = { userMessageId: "q1", live: { ...EMPTY_LIVE, failed: true } };
    expect(handedOver(pending, [{ id: "a0", role: "assistant" }, question])).toBe(false);
  });
});
