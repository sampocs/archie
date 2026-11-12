import { makeCardsAnswerId } from "./makeCards";

const question = (id: string) => ({ id, role: "user", status: "complete" });
const answer = (id: string, status = "complete") => ({ id, role: "assistant", status });
const base = { hasCardSet: () => false, aboutKind: null, questionInFlight: false };

describe("makeCardsAnswerId", () => {
  it("is the last answer only, not every earlier one", () => {
    const turns = [question("q1"), answer("a1"), question("q2"), answer("a2")];
    expect(makeCardsAnswerId({ ...base, turns })).toBe("a2");
  });

  it("is none in a chat about a review card", () => {
    expect(makeCardsAnswerId({ ...base, turns: [question("q1"), answer("a1")], aboutKind: "card" })).toBeNull();
  });

  it("is none while a question is in flight, or when the chat ends on a question", () => {
    expect(makeCardsAnswerId({ ...base, turns: [question("q1"), answer("a1")], questionInFlight: true })).toBeNull();
    expect(makeCardsAnswerId({ ...base, turns: [question("q1"), answer("a1"), question("q2")] })).toBeNull();
  });

  it("is none when the last answer failed or already proposed cards", () => {
    expect(makeCardsAnswerId({ ...base, turns: [question("q1"), answer("a1", "failed")] })).toBeNull();
    const turns = [question("q1"), answer("a1")];
    expect(makeCardsAnswerId({ ...base, turns, hasCardSet: (id) => id === "a1" })).toBeNull();
  });

  it("is offered in a chat about a note or source", () => {
    expect(makeCardsAnswerId({ ...base, turns: [question("q1"), answer("a1")], aboutKind: "source" })).toBe("a1");
  });
});
