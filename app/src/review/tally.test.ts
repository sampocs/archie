import { gradedCount, tallyOf } from "./tally";

describe("tallyOf", () => {
  it("counts each outcome", () => {
    const tally = tallyOf([
      { cardId: "a", outcome: "got_it" },
      { cardId: "b", outcome: "got_it" },
      { cardId: "c", outcome: "partly" },
      { cardId: "d", outcome: "missed" },
    ]);
    expect(tally).toEqual({ gotIt: 2, partly: 1, missed: 1, dropped: 0 });
    expect(gradedCount(tally)).toBe(4);
  });

  it("a later entry for the same card replaces the earlier one", () => {
    const tally = tallyOf([
      { cardId: "a", outcome: "partly" },
      { cardId: "b", outcome: "missed" },
      { cardId: "a", outcome: "got_it" },
    ]);
    expect(tally).toEqual({ gotIt: 1, partly: 0, missed: 1, dropped: 0 });
  });

  it("counts dropped cards separately from graded ones", () => {
    const tally = tallyOf([
      { cardId: "a", outcome: "dropped" },
      { cardId: "b", outcome: "got_it" },
    ]);
    expect(tally).toEqual({ gotIt: 1, partly: 0, missed: 0, dropped: 1 });
    expect(gradedCount(tally)).toBe(1);
  });
});
