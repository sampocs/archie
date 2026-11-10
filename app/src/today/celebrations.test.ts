import { celebratedOn, storedCelebrations } from "./celebrations";

describe("celebration memory", () => {
  it("is empty before anything was stored", () => {
    expect(celebratedOn(null, "2026-11-05")).toEqual(new Set());
  });

  it("keeps what was celebrated earlier the same day, once each", () => {
    const stored = storedCelebrations("2026-11-05", ["review", "brief", "review"]);

    expect(celebratedOn(stored, "2026-11-05")).toEqual(new Set(["review", "brief"]));
  });

  it("treats a garbage stored value as empty", () => {
    expect(celebratedOn("garbage", "2026-11-05")).toEqual(new Set());
    expect(celebratedOn('{"day":5}', "2026-11-05")).toEqual(new Set());
  });

  it("forgets yesterday's celebrations once the local day turns", () => {
    const stored = storedCelebrations("2026-11-04", ["review", "day"]);

    expect(celebratedOn(stored, "2026-11-05")).toEqual(new Set());
  });
});
