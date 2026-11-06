import { canSaveTake } from "./editor";

describe("canSaveTake", () => {
  it("needs a title and a body", () => {
    expect(canSaveTake({ title: "", body: "x" })).toBe(false);
    expect(canSaveTake({ title: "x", body: "" })).toBe(false);
    expect(canSaveTake({ title: "x", body: "y" })).toBe(true);
  });

  it("refuses a body the server would reject, counting the trimmed text by code point", () => {
    expect(canSaveTake({ title: "x", body: "a".repeat(20_000) })).toBe(true);
    expect(canSaveTake({ title: "x", body: "a".repeat(20_001) })).toBe(false);
    expect(canSaveTake({ title: "x", body: `  \n${"a".repeat(20_000)}\n  ` })).toBe(true);
    expect(canSaveTake({ title: "x", body: "😀".repeat(20_000) })).toBe(true);
  });

  it("ignores whitespace-only text", () => {
    expect(canSaveTake({ title: "  \n", body: "y" })).toBe(false);
    expect(canSaveTake({ title: "x", body: " \t " })).toBe(false);
  });
});
