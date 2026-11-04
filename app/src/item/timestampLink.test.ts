import { timestampSeconds, timestampUrl } from "./timestampLink";

describe("timestampSeconds", () => {
  it("parses minutes and hours", () => {
    expect(timestampSeconds("12:14")).toBe(734);
    expect(timestampSeconds("1:02:03")).toBe(3723);
    expect(timestampSeconds("00:10")).toBe(10);
  });

  it("rejects junk", () => {
    expect(timestampSeconds("soon")).toBeNull();
    expect(timestampSeconds("12")).toBeNull();
  });
});

describe("timestampUrl", () => {
  it("replaces t on a YouTube watch URL and keeps v", () => {
    const url = timestampUrl({ kind: "youtube", url: "https://www.youtube.com/watch?v=abc&t=5" }, "1:02:03");
    const parsed = new URL(url);
    expect(parsed.searchParams.get("t")).toBe("3723");
    expect(parsed.searchParams.get("v")).toBe("abc");
  });

  it("adds t to a youtu.be link", () => {
    expect(timestampUrl({ kind: "youtube", url: "https://youtu.be/abc" }, "00:10")).toBe("https://youtu.be/abc?t=10");
  });

  it("adds t to a Spotify episode", () => {
    const url = timestampUrl({ kind: "podcast", url: "https://open.spotify.com/episode/xyz" }, "12:14");
    expect(url).toBe("https://open.spotify.com/episode/xyz?t=734");
  });

  it("leaves other podcast links alone", () => {
    const url = "https://podcasts.apple.com/us/podcast/x/id1?i=2";
    expect(timestampUrl({ kind: "podcast", url }, "12:14")).toBe(url);
  });

  it("leaves the URL alone for an unparseable timestamp", () => {
    const url = "https://youtu.be/abc";
    expect(timestampUrl({ kind: "youtube", url }, "later")).toBe(url);
  });
});
