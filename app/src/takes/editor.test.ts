import { canSaveTake } from "./editor";

describe("canSaveTake", () => {
  it("needs a title and a body", () => {
    expect(canSaveTake({ title: "", body: "x" })).toBe(false);
    expect(canSaveTake({ title: "x", body: "" })).toBe(false);
    expect(canSaveTake({ title: "x", body: "y" })).toBe(true);
  });

  it("ignores whitespace-only text", () => {
    expect(canSaveTake({ title: "  \n", body: "y" })).toBe(false);
    expect(canSaveTake({ title: "x", body: " \t " })).toBe(false);
  });
});
