import { splitFacts } from "./figures";

const figures = (sentence: string) =>
  splitFacts(sentence)
    .filter((segment) => segment.figure)
    .map((segment) => segment.text);

describe("splitFacts", () => {
  it("sets counts in mono but leaves the clock time plain", () => {
    expect(figures("Democrats on track for 228 House seats and 54 Senate seats as of 5am ET.")).toEqual(["228", "54"]);
  });

  it("keeps a dollar amount with its unit together", () => {
    expect(figures("Raised $6.34 billion in the round.")).toEqual(["$6.34 billion"]);
  });

  it("keeps percents, signed bps and k+ suffixes whole", () => {
    expect(figures("Odds at 98%, yield 4.952%, up +6.0 bps, and $45k+ raised.")).toEqual([
      "98%",
      "4.952%",
      "+6.0 bps",
      "$45k+",
    ]);
  });

  it("round-trips the sentence and skips digits glued to a word", () => {
    const sentence = "Q3 sales of 1,200 units";
    expect(splitFacts(sentence).map((segment) => segment.text).join("")).toBe(sentence);
    expect(figures(sentence)).toEqual(["1,200"]);
  });
});
