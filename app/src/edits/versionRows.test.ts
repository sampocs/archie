import { sheetTitle, versionRowDetail, versionRowTitle } from "./versionRows";

const entry = (overrides: object) => ({
  version: 3,
  createdAt: new Date(2026, 10, 8).toISOString(),
  origin: "chat_edit" as const,
  instruction: "Drop the jargon",
  content: null,
  current: true,
  ...overrides,
});

describe("version rows", () => {
  it("titles a row by its number and date", () => {
    expect(versionRowTitle(entry({}), new Date(2026, 10, 9))).toBe("Version 3 · Nov 8");
  });

  it("says how a version was made, with the edit's description when there is one", () => {
    expect(versionRowDetail(entry({}))).toBe("Edited in Ask · Drop the jargon");
    expect(versionRowDetail(entry({ origin: "archie", instruction: null }))).toBe("Archie");
    expect(versionRowDetail(entry({ origin: "care", instruction: "rates matter" }))).toBe(
      "Rewritten from your note · rates matter",
    );
  });

  it("names each kind's sheet", () => {
    expect(["summary", "primer", "topic_primer", "card", "take"].map((kind) => sheetTitle(kind as never))).toEqual([
      "Summary versions",
      "Primer versions",
      "Primer versions",
      "Card versions",
      "Earlier versions",
    ]);
  });
});
