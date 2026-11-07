import { formatClock, parseSegments } from "./types";

describe("formatClock", () => {
  it("shows minutes and seconds, and hours once there are any", () => {
    expect([formatClock(0), formatClock(1880.6), formatClock(3723)]).toEqual(["0:00", "31:20", "1:02:03"]);
  });
});

describe("parseSegments", () => {
  it("keeps well-formed segments and drops the rest", () => {
    const good = { label: "web", text: "T", citations: [] };
    expect(parseSegments(JSON.stringify([good, { label: "other", text: "x", citations: [] }, 3]))).toEqual([good]);
    expect([parseSegments(null), parseSegments("{oops")]).toEqual([[], []]);
  });
});
