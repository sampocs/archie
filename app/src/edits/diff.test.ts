import { foldUnchanged, lineDiff } from "./diff";

describe("lineDiff", () => {
  it("marks a removed line and keeps the rest in order", () => {
    expect(lineDiff(["Gist", "g", "Key ideas", "• a", "• b", "• c"], ["Gist", "g", "Key ideas", "• a", "• c"])).toEqual([
      { kind: "same", text: "Gist" },
      { kind: "same", text: "g" },
      { kind: "same", text: "Key ideas" },
      { kind: "same", text: "• a" },
      { kind: "removed", text: "• b" },
      { kind: "same", text: "• c" },
    ]);
  });

  it("shows a changed line as the old one removed, then the new one added", () => {
    expect(lineDiff(["Question: Q?", "Answer: A."], ["Question: Q?", "Answer: B."])).toEqual([
      { kind: "same", text: "Question: Q?" },
      { kind: "removed", text: "Answer: A." },
      { kind: "added", text: "Answer: B." },
    ]);
  });

  it("handles an empty side", () => {
    expect(lineDiff([], ["x"])).toEqual([{ kind: "added", text: "x" }]);
    expect(lineDiff(["x"], [])).toEqual([{ kind: "removed", text: "x" }]);
  });
});

describe("foldUnchanged", () => {
  it("keeps one line of context around a change and folds the rest into counted gaps", () => {
    const lines = lineDiff(["1", "2", "3", "4", "5", "6", "7"], ["1", "2", "3", "4x", "5", "6", "7"]);
    expect(foldUnchanged(lines)).toEqual([
      { kind: "gap", count: 2 },
      { kind: "same", text: "3" },
      { kind: "removed", text: "4" },
      { kind: "added", text: "4x" },
      { kind: "same", text: "5" },
      { kind: "gap", count: 2 },
    ]);
  });

  it("folds an unchanged text into one gap", () => {
    expect(foldUnchanged(lineDiff(["a", "b"], ["a", "b"]))).toEqual([{ kind: "gap", count: 2 }]);
  });
});
