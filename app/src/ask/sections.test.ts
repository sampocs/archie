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
  thinkingLabel,
  type LiveAnswer,
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

    expect(liveView(streaming)).toEqual({ sections: [], streamingText: "It buys bonds.", thinking: null });

    const finished = applyEvent(streaming, { type: "block", block: 0, label: "library", citations: [library()] });
    expect(liveView(finished).sections).toEqual([{ label: "library", text: "It buys bonds.", citations: [library()] }]);
    expect(applyEvent(finished, { type: "done", message_id: "m2" }).messageId).toBe("m2");
    expect(applyEvent(finished, { type: "error", message: "x" }).failed).toBe(true);
  });

  it("labels the thinking row by the search running, until text arrives", () => {
    const live = applyEvent(EMPTY_LIVE, { type: "searching", kind: "web", query: "fed funds rate" });
    expect(liveView(live).thinking).toBe("Searching the web…");
    expect(liveView(applyEvent(live, { type: "delta", block: 0, text: "About" })).thinking).toBeNull();
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
    expect(liveView(drafting).thinking).toBe("Drafting an edit…");
    expect(liveView(proposed).thinking).toBe("Thinking");

    const searched = applyEvent(drafting, { type: "searching", kind: "library", query: "x" });
    expect(searched.editing).toBe(false);
    expect(searched.searching).toBe("library");
  });
});

describe("edit events for one target", () => {
  const base = {
    type: "edit" as const,
    target_kind: "summary" as const,
    target_id: "s1",
    title: "T",
    description: "D",
    base_version: 1,
    before: {},
    after: {},
    status: "proposed" as const,
  };

  it("supersedes the earlier proposed one, keeps other targets, and doesn't duplicate a repeated id", () => {
    const same = applyEvent(applyEvent(EMPTY_LIVE, { ...base, id: "a" }), { ...base, id: "b" });
    expect(same.proposals.map((proposal) => [proposal.id, proposal.status])).toEqual([
      ["a", "superseded"],
      ["b", "proposed"],
    ]);

    const other = applyEvent(applyEvent(EMPTY_LIVE, { ...base, id: "a" }), { ...base, id: "b", target_id: "s2" });
    expect(other.proposals.map((proposal) => proposal.status)).toEqual(["proposed", "proposed"]);

    const repeated = applyEvent(applyEvent(EMPTY_LIVE, { ...base, id: "a" }), { ...base, id: "a" });
    expect(repeated.proposals).toHaveLength(1);
    expect(repeated.proposals[0].status).toBe("proposed");
  });
});

describe("card-set events", () => {
  const cardSet = (overrides: { id: string; status?: string }) => ({
    conversation_id: "k1",
    message_id: "m1",
    title: "JWT vs session tokens",
    cheat_sheet: "## The difference",
    cards: [{ kind: "concept", question: "Q?", answer: "A." }],
    status: "proposed",
    saved_source_id: null,
    kept: null,
    created_at: "x",
    updated_at: "x",
    change_seq: 1,
    ...overrides,
  });

  it("drafting_cards labels the row, and a cards event adds its set and stops drafting", () => {
    const drafting = applyEvent(EMPTY_LIVE, { type: "drafting_cards" });
    expect(drafting.draftingCards).toBe(true);
    expect(liveView(drafting).thinking).toBe("Drafting cards…");

    const proposed = applyEvent(drafting, { type: "cards", ...cardSet({ id: "a" }) });
    expect(proposed.draftingCards).toBe(false);
    expect(proposed.cardSets).toEqual([cardSet({ id: "a" })]);
  });

  it("text, a search, an edit draft and the end of the answer each stop drafting cards", () => {
    const drafting = applyEvent(EMPTY_LIVE, { type: "drafting_cards" });
    expect(applyEvent(drafting, { type: "delta", block: 0, text: "Here" }).draftingCards).toBe(false);
    expect(applyEvent(drafting, { type: "searching", kind: "library", query: "jwt" }).draftingCards).toBe(false);
    expect(applyEvent(drafting, { type: "editing", target_kind: null }).draftingCards).toBe(false);
    expect(applyEvent(drafting, { type: "done", message_id: "m2" }).draftingCards).toBe(false);
    expect(applyEvent(drafting, { type: "error", message: "x" }).draftingCards).toBe(false);
    expect(endOfStream(drafting).draftingCards).toBe(false);
  });

  it("a newer set replaces the still-proposed ones, leaves a saved one, and a repeated id isn't added twice", () => {
    const withSaved = applyEvent(EMPTY_LIVE, { type: "cards", ...cardSet({ id: "saved", status: "saved" }) });
    const two = applyEvent(applyEvent(withSaved, { type: "cards", ...cardSet({ id: "a" }) }), {
      type: "cards",
      ...cardSet({ id: "b" }),
    });
    expect(two.cardSets.map((set) => [set.id, set.status])).toEqual([
      ["saved", "saved"],
      ["a", "replaced"],
      ["b", "proposed"],
    ]);

    const repeated = applyEvent(applyEvent(EMPTY_LIVE, { type: "cards", ...cardSet({ id: "a" }) }), {
      type: "cards",
      ...cardSet({ id: "a" }),
    });
    expect(repeated.cardSets.map((set) => [set.id, set.status])).toEqual([["a", "proposed"]]);
  });
});

describe("thinkingLabel", () => {
  const live = (overrides: Partial<LiveAnswer>): LiveAnswer => ({ ...EMPTY_LIVE, ...overrides });

  it("reads Thinking from send until text streams, then hides", () => {
    expect(thinkingLabel(EMPTY_LIVE, false)).toBe("Thinking");
    expect(thinkingLabel(EMPTY_LIVE, true)).toBeNull();
  });

  it("names the tool running, even after text has streamed", () => {
    expect(thinkingLabel(live({ searching: "library" }), true)).toBe("Searching your library…");
    expect(thinkingLabel(live({ editing: true }), true)).toBe("Drafting an edit…");
    expect(thinkingLabel(live({ draftingCards: true }), true)).toBe("Drafting cards…");
  });

  it("hides once the answer is done or failed, whatever was running", () => {
    expect(thinkingLabel(live({ messageId: "m2" }), false)).toBeNull();
    expect(thinkingLabel(live({ failed: true, draftingCards: true }), false)).toBeNull();
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
