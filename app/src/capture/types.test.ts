import { chooseIntent, EMPTY_CHOICE } from "./types";

describe("chooseIntent", () => {
  const finished = {
    intent: "finished" as const,
    reaction: "easy" as const,
    note: "good",
    queuePrimer: true,
  };

  it("clears reaction, note and queuePrimer when the intent changes", () => {
    expect(chooseIntent(finished, "queue")).toEqual({
      ...EMPTY_CHOICE,
      intent: "queue",
    });
  });

  it("keeps the answers when the same intent is re-selected", () => {
    expect(chooseIntent(finished, "finished")).toBe(finished);
  });
});
