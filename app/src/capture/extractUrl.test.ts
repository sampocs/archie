import { extractFirstUrl } from "./extractUrl";

describe("extractFirstUrl", () => {
  it("finds the URL in Spotify share text", () => {
    expect(extractFirstUrl("Listen to this https://open.spotify.com/episode/x?si=1")).toBe(
      "https://open.spotify.com/episode/x?si=1",
    );
  });

  it("trims trailing punctuation from a URL in parentheses and takes only the first URL", () => {
    expect(extractFirstUrl('See (https://example.com/a.b), or "https://other.com"')).toBe("https://example.com/a.b");
  });

  it("returns null when there is no URL", () => {
    expect(extractFirstUrl("nothing to see, ftp://x.com")).toBeNull();
  });
});
