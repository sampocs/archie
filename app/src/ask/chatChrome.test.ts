import { backLabelOf, showsSectionLabel } from "./chatChrome";

describe("backLabelOf", () => {
  it("is the note's title when the chat opened from the note", () => {
    expect(backLabelOf("note-1", "Liquid Staking")).toBe("Liquid Staking");
  });

  it("is Ask otherwise, or when the title is unknown", () => {
    expect(backLabelOf(undefined, "Liquid Staking")).toBe("Ask");
    expect(backLabelOf("note-1", null)).toBe("Ask");
  });
});

describe("showsSectionLabel", () => {
  const cited = { label: "background" as const, citations: [{ kind: "web" as const, title: "t", url: "u", quote: null }] };

  it("hides an uncited background label only when quiet", () => {
    expect(showsSectionLabel({ label: "background", citations: [] }, true)).toBe(false);
    expect(showsSectionLabel({ label: "background", citations: [] }, false)).toBe(true);
  });

  it("keeps cited background and other labels", () => {
    expect(showsSectionLabel(cited, true)).toBe(true);
    expect(showsSectionLabel({ label: "library", citations: [] }, true)).toBe(true);
  });
});
