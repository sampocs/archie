import { sourceRow } from "@/library/testRows";

import { makeCardsAction } from "./cardsMenu";

const ready = { processing: "ready", cardsOff: 0, state: "consumed" };

describe("makeCardsAction", () => {
  it("is hidden until the source is ready", () => {
    expect(makeCardsAction(sourceRow({ ...ready, processing: "processing", cardsOff: 1 }), 0)).toBeNull();
  });

  it("is hidden when the source has cards and they are on", () => {
    expect(makeCardsAction(sourceRow(ready), 3)).toBeNull();
  });

  it("goes deeper on an inbox or briefed item with no cards", () => {
    for (const state of ["inbox", "briefed"]) {
      expect(makeCardsAction(sourceRow({ ...ready, state }), 0)).toEqual({
        kind: "go_deeper",
        subtitle: "Marks it done and writes a primer",
      });
    }
  });

  it("turns cards back on for a done item whose cards are off, even with leftover cards", () => {
    expect(makeCardsAction(sourceRow({ ...ready, cardsOff: 1 }), 2)).toEqual({
      kind: "cards_on",
      subtitle: "Writes cards for this again",
    });
  });

  it("turns cards on for a done item with none", () => {
    expect(makeCardsAction(sourceRow(ready), 0)?.kind).toBe("cards_on");
  });
});
