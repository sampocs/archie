import { waitingBanner, type WaitingRow, type WaitingSource } from "./waiting";

const note = (overrides: Partial<WaitingSource>): WaitingSource => ({
  id: "n1",
  title: "Pricing Power",
  url: "https://example.com/n1",
  kind: "note",
  deletedAt: null,
  cardsOff: 0,
  ...overrides,
});
const waiting = (sourceId: string, waitingAt: string): WaitingRow => ({ sourceId, waitingAt });

describe("waitingBanner", () => {
  it("is null when nothing waits", () => {
    expect(waitingBanner([], [note({})])).toBeNull();
  });

  it("names the one waiting note", () => {
    expect(waitingBanner([waiting("n1", "2026-11-20T10:00:00Z")], [note({})])).toEqual({
      sourceId: "n1",
      title: "Pricing Power",
      count: 1,
    });
  });

  it("offers the oldest waiting note first and counts all of them", () => {
    const sources = [note({ id: "a", title: "Newer" }), note({ id: "b", title: "Older" }), note({ id: "c", title: "Newest" })];
    const rows = [waiting("a", "2026-11-20T10:00:00Z"), waiting("c", "2026-11-21T10:00:00Z"), waiting("b", "2026-11-19T10:00:00Z")];

    expect(waitingBanner(rows, sources)).toEqual({ sourceId: "b", title: "Older", count: 3 });
  });

  it("drops rows whose note is missing, deleted, has cards off, or is not a note", () => {
    const sources = [
      note({ id: "deleted", deletedAt: "2026-11-20T00:00:00Z" }),
      note({ id: "off", cardsOff: 1 }),
      note({ id: "article", kind: "article" }),
      note({ id: "kept", title: "Kept" }),
    ];
    const rows = [
      waiting("gone", "2026-11-01T00:00:00Z"),
      waiting("deleted", "2026-11-02T00:00:00Z"),
      waiting("off", "2026-11-03T00:00:00Z"),
      waiting("article", "2026-11-04T00:00:00Z"),
      waiting("kept", "2026-11-05T00:00:00Z"),
    ];

    expect(waitingBanner(rows, sources)).toEqual({ sourceId: "kept", title: "Kept", count: 1 });
  });

  it("is null when every waiting note was dropped", () => {
    expect(waitingBanner([waiting("n1", "2026-11-20T10:00:00Z")], [note({ deletedAt: "2026-11-20T11:00:00Z" })])).toBeNull();
  });

  it("falls back to the url for an untitled note", () => {
    expect(waitingBanner([waiting("n1", "2026-11-20T10:00:00Z")], [note({ title: null })])).toMatchObject({
      title: "https://example.com/n1",
    });
  });
});
