import { shownStatus, targetHref } from "./proposalState";

describe("shownStatus", () => {
  it("shows a proposal as stale once this phone's copy of the target moved past its base version", () => {
    expect(shownStatus({ status: "proposed", baseVersion: 1 }, 1)).toBe("proposed");
    expect(shownStatus({ status: "proposed", baseVersion: 1 }, 2)).toBe("stale");
    expect(shownStatus({ status: "proposed", baseVersion: 2 }, 1)).toBe("proposed");
  });

  it("trusts the server's status otherwise, and waits while the target hasn't loaded", () => {
    expect(shownStatus({ status: "proposed", baseVersion: 1 }, null)).toBe("proposed");
    expect(shownStatus({ status: "applied", baseVersion: 1 }, 2)).toBe("applied");
    expect(shownStatus({ status: "undone", baseVersion: 1 }, 3)).toBe("undone");
  });
});

it("opens each kind's own page", () => {
  expect(["summary", "primer", "topic_primer", "take", "card"].map((kind) => targetHref(kind as never, "x"))).toEqual([
    "/source/x",
    "/primer/x",
    "/topic/x",
    "/take/x",
    "/review/session?mode=card&id=x",
  ]);
});
