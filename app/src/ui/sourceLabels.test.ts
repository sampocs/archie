import { datedByline, itemBadge, kindLabel, sourceByline, sourceMeta } from "./sourceLabels";

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

describe("datedByline", () => {
  // jest.config.js pins TZ to America/New_York.
  const now = new Date(2026, 10, 4, 9);

  it("gives a newsletter its full send date, however old, from its Date header when it has one", () => {
    const createdAt = new Date(2026, 9, 21, 7).toISOString();
    const newsletter = { kind: "newsletter", url: "newsletter:1", sender: "Morning Brew", createdAt };
    expect(datedByline({ ...newsletter, publishedAt: null }, now)).toBe("Morning Brew · Wed, Oct 21");
    const publishedAt = new Date(2026, 9, 20, 6).toISOString();
    expect(datedByline({ ...newsletter, publishedAt }, now)).toBe("Morning Brew · Tue, Oct 20");
  });

  it("says when anything else was added: the weekday within six days, else the date", () => {
    const pod = { kind: "podcast", url: "https://open.spotify.com/episode/1", sender: null, publishedAt: null };
    expect(datedByline({ ...pod, createdAt: new Date(2026, 10, 2, 8).toISOString() }, now)).toBe(
      "open.spotify.com · Added Mon",
    );
    expect(datedByline({ ...pod, createdAt: new Date(2026, 9, 25, 8).toISOString() }, now)).toBe(
      "open.spotify.com · Added Oct 25",
    );
  });
});

describe("itemBadge", () => {
  it.each([
    ["inbox", "Inbox"],
    ["briefed", "Inbox"],
    ["queued", "Queued"],
    ["consumed", "Done"],
  ])("%s → %s", (state, badge) => {
    expect(itemBadge(state)).toBe(badge);
  });
});
