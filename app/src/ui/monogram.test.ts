import { monogramFor } from "./monogram";

const base = { kind: "article", title: null, sender: null, url: "https://www.example.com/a" };

describe("monogramFor", () => {
  it("prefers the sender, then the title, then the site", () => {
    expect(monogramFor({ ...base, kind: "newsletter", sender: "Morning Brew", title: "Zed" })).toBe("M");
    expect(monogramFor({ ...base, title: "  how to" })).toBe("H");
    expect(monogramFor(base)).toBe("E");
  });

  it("uses a play glyph for YouTube and skips leading emoji", () => {
    expect(monogramFor({ ...base, kind: "youtube", title: "Video" })).toBe("▶");
    expect(monogramFor({ ...base, title: "🔥 hot take" })).toBe("H");
  });

  it("falls back to a question mark", () => {
    expect(monogramFor({ ...base, url: "not a url" })).toBe("?");
  });

  it("uses a pencil glyph for notes", () => {
    expect(monogramFor({ ...base, kind: "note", title: "Zed" })).toBe("✎");
  });
});
