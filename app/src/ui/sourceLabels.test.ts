import { datedByline, itemBadge, kindLabel, longDate, sourceByline, sourceMeta } from "./sourceLabels";

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

  it("gives a newsletter its full send date, however old", () => {
    const createdAt = new Date(2026, 9, 21, 7).toISOString();
    expect(datedByline({ kind: "newsletter", url: "newsletter:1", sender: "Morning Brew", createdAt }, now)).toBe(
      "Morning Brew · Wed, Oct 21",
    );
  });

  it("says when anything else was added: the weekday within six days, else the date", () => {
    const pod = { kind: "podcast", url: "https://open.spotify.com/episode/1", sender: null };
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

describe("notes", () => {
  const note = { kind: "note", url: "bear://x-callback-url/open-note?id=1", sender: null };

  it("labels a note as Notes from Bear, with its edit date", () => {
    const edited = new Date(2024, 1, 13, 12).toISOString();
    expect(kindLabel("note")).toBe("Notes");
    expect(sourceByline(note)).toBe("Bear");
    expect(datedByline({ ...note, createdAt: "2025-01-01T00:00:00Z", noteEditedAt: edited }, new Date())).toBe(
      "From Bear · edited Feb 13, 2024",
    );
  });

  it("falls back to the created date when the edit date is missing", () => {
    const created = new Date(2024, 1, 13, 12).toISOString();
    expect(datedByline({ ...note, createdAt: created, noteEditedAt: null }, new Date())).toBe(
      "From Bear · edited Feb 13, 2024",
    );
  });

  it("formats a long date in local time", () => {
    expect(longDate(new Date(2024, 1, 13, 12).toISOString())).toBe("Feb 13, 2024");
  });
});
