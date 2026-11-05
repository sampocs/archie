import { readingMinutes, wordCount } from "./primer";

describe("readingMinutes", () => {
  it("rounds words / 220 up, with a one-minute floor", () => {
    expect(readingMinutes(0)).toBe(1);
    expect(readingMinutes(220)).toBe(1);
    expect(readingMinutes(221)).toBe(2);
    expect(readingMinutes(1320)).toBe(6);
  });
});

describe("wordCount", () => {
  it("counts whitespace-separated words across lines and markdown marks", () => {
    expect(wordCount("# Grid\n\n**Power** sets  the\tpace.\n- one")).toBe(8);
    expect(wordCount("  \n ")).toBe(0);
  });
});
