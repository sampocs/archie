import {
  allKept,
  asCardSetMode,
  cardSetBlock,
  cardSetValues,
  keptIndices,
  pageLabel,
  saveLabel,
  shownCardSetStatus,
  stepPage,
  toggleKept,
  viewOfCardSetRow,
  type CardSetView,
} from "./cardSets";

const cards = [
  { kind: "concept", question: "Why is a JWT hard to revoke?", answer: "Nothing is looked up." },
  { kind: "concept", question: "What does a session store hold?", answer: "The session itself." },
  { kind: "foundation", question: "Where should a browser keep auth cookies?", answer: "httpOnly cookies." },
];

const view = (overrides: Partial<CardSetView>): CardSetView => ({
  id: "cs1",
  title: "JWT vs session tokens",
  cheatSheet: "## The difference",
  cards,
  status: "proposed",
  savedSourceId: null,
  kept: null,
  ...overrides,
});

describe("keeping cards and the Save count", () => {
  it("starts with every card kept, and Save counts them all", () => {
    const kept = allKept(cards.length);
    expect(keptIndices(kept)).toEqual([0, 1, 2]);
    expect(saveLabel(keptIndices(kept).length, false)).toBe("Save 3");
  });

  it("unticking a card drops it from what Save sends, and ticking it again brings it back", () => {
    const unticked = toggleKept(allKept(cards.length), 1);
    expect(keptIndices(unticked)).toEqual([0, 2]);
    expect(saveLabel(keptIndices(unticked).length, false)).toBe("Save 2");
    expect(keptIndices(toggleKept(unticked, 1))).toEqual([0, 1, 2]);
  });

  it("reads Update when the chat already saved its item", () => {
    expect(saveLabel(2, true)).toBe("Update 2");
  });

  it("keeps nothing once every card is unticked", () => {
    const none = [0, 1, 2].reduce(toggleKept, allKept(cards.length));
    expect(keptIndices(none)).toEqual([]);
  });
});

describe("the pager", () => {
  it("steps one card at a time, held to the first and last", () => {
    expect(stepPage(0, 1, 5)).toBe(1);
    expect(stepPage(4, 1, 5)).toBe(4);
    expect(stepPage(0, -1, 5)).toBe(0);
    expect(stepPage(3, -1, 5)).toBe(2);
  });

  it("labels the page one-based", () => {
    expect(pageLabel(0, 5)).toBe("1 / 5");
    expect(pageLabel(3, 5)).toBe("4 / 5");
  });

  it("remembers only a list choice; anything else is one at a time", () => {
    expect(asCardSetMode("list")).toBe("list");
    expect(asCardSetMode("pager")).toBe("pager");
    expect(asCardSetMode(null)).toBe("pager");
    expect(asCardSetMode("grid")).toBe("pager");
  });
});

describe("cardSetBlock", () => {
  it("shows a proposed set in full", () => {
    expect(cardSetBlock(view({}))).toEqual({ kind: "proposed" });
  });

  it("collapses a replaced set to one line", () => {
    expect(cardSetBlock(view({ status: "replaced" }))).toEqual({
      kind: "collapsed",
      left: "Earlier proposal",
      right: "Replaced",
    });
  });

  it("collapses a still-proposed stored set once the live answer holds a newer one", () => {
    expect(shownCardSetStatus(view({}), true)).toBe("replaced");
    expect(cardSetBlock(view({}), true)).toEqual({ kind: "collapsed", left: "Earlier proposal", right: "Replaced" });
  });

  it("keeps a saved or discarded set as it ended, whatever the live answer holds", () => {
    expect(shownCardSetStatus(view({ status: "saved" }), true)).toBe("saved");
    expect(cardSetBlock(view({ status: "discarded" }), true)).toEqual({
      kind: "collapsed",
      left: "Cheat sheet · JWT vs session tokens",
      right: "Discarded",
    });
  });

  it("says how many cards a saved set kept, and links its item", () => {
    expect(cardSetBlock(view({ status: "saved", kept: [0, 2], savedSourceId: "s9" }))).toEqual({
      kind: "saved",
      line: "✓ Saved · 2 cards in review",
      itemId: "s9",
    });
    expect(cardSetBlock(view({ status: "saved", kept: [1], savedSourceId: "s9" }))).toMatchObject({
      line: "✓ Saved · 1 card in review",
    });
  });
});

describe("stored rows", () => {
  const pulled = {
    id: "cs1",
    conversation_id: "k1",
    message_id: "m1",
    title: "JWT vs session tokens",
    cheat_sheet: "## The difference",
    cards,
    status: "saved",
    saved_source_id: "s9",
    kept: [0, 2],
    created_at: "2026-11-09T10:00:00Z",
    updated_at: "2026-11-09T10:05:00Z",
    change_seq: 7,
  };

  it("reads back what it stored", () => {
    expect(viewOfCardSetRow({ id: pulled.id, ...cardSetValues(pulled) })).toEqual({
      id: "cs1",
      title: "JWT vs session tokens",
      cheatSheet: "## The difference",
      cards,
      status: "saved",
      savedSourceId: "s9",
      kept: [0, 2],
    });
  });

  it("stores a set that isn't saved yet with no kept list", () => {
    expect(cardSetValues({ ...pulled, status: "proposed", saved_source_id: null, kept: null }).kept).toBeNull();
  });

  it("skips a row whose status this phone doesn't know", () => {
    expect(viewOfCardSetRow({ id: pulled.id, ...cardSetValues({ ...pulled, status: "archived" }) })).toBeNull();
  });
});
