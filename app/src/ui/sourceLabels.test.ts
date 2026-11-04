import { kindLabel, sourceByline, sourceMeta, stateLabel } from "./sourceLabels";

describe("sourceByline", () => {
  it("uses a newsletter's sender, or 'Newsletter' without one", () => {
    expect(sourceByline({ kind: "newsletter", url: "https://x.test/a", sender: "Ben <ben@x.test>" })).toBe(
      "Ben <ben@x.test>",
    );
    expect(sourceByline({ kind: "newsletter", url: "https://x.test/a", sender: null })).toBe("Newsletter");
  });

  it("uses the hostname without www for other kinds, and the raw url when it does not parse", () => {
    expect(sourceByline({ kind: "article", url: "https://www.paulgraham.com/greatwork.html", sender: null })).toBe(
      "paulgraham.com",
    );
    expect(sourceByline({ kind: "podcast", url: "https://open.spotify.com/episode/1", sender: null })).toBe(
      "open.spotify.com",
    );
    expect(sourceByline({ kind: "link", url: "not a url", sender: null })).toBe("not a url");
  });
});

describe("stateLabel", () => {
  it("maps the known states and capitalizes the rest", () => {
    expect(stateLabel("inbox")).toBe("Inbox");
    expect(stateLabel("queued")).toBe("Queued");
    expect(stateLabel("consumed")).toBe("Done");
    expect(stateLabel("archived")).toBe("Archived");
  });
});

describe("kindLabel and sourceMeta", () => {
  it("labels each kind, defaulting to Link", () => {
    expect(["podcast", "youtube", "article", "x", "newsletter", "other"].map(kindLabel)).toEqual([
      "Podcast",
      "YouTube",
      "Article",
      "X post",
      "Newsletter",
      "Link",
    ]);
  });

  it("joins the label and byline", () => {
    expect(sourceMeta({ kind: "newsletter", url: "https://x.test", sender: "Morning Brew" })).toBe(
      "Newsletter · Morning Brew",
    );
  });
});
