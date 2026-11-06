import {
  defaultCollectionId,
  formatDuration,
  groupCollections,
  isVideo,
  mosaicImages,
  postByline,
  postSourceLabel,
  savedCountLabel,
  savedDate,
  type CollectionItemRow,
  type CollectionRow,
  type CollectionWithItems,
} from "./collections";

const collectionRow = (overrides: Partial<CollectionRow>): CollectionRow => ({
  id: "c1",
  name: "Bears hype",
  position: 0,
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  deletedAt: null,
  ...overrides,
});

const itemRow = (overrides: Partial<CollectionItemRow>): CollectionItemRow => ({
  id: "i1",
  collectionId: "c1",
  url: "https://example.com/a",
  kind: "link",
  title: null,
  author: null,
  imageUrl: null,
  durationSeconds: null,
  note: null,
  metadataStatus: "ready",
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  deletedAt: null,
  ...overrides,
});

const withItems = (items: CollectionItemRow[]): CollectionWithItems => ({ ...collectionRow({}), items });

describe("groupCollections", () => {
  it("lists live collections in tile order, each with its live posts newest first", () => {
    const collections = [
      collectionRow({ id: "late", position: 1, createdAt: "2026-11-01T00:00:00Z" }),
      collectionRow({ id: "tie-newer", position: 0, createdAt: "2026-11-03T00:00:00Z" }),
      collectionRow({ id: "tie-older", position: 0, createdAt: "2026-11-02T00:00:00Z" }),
      collectionRow({ id: "gone", position: 0.5, deletedAt: "2026-11-04T00:00:00Z" }),
    ];
    const items = [
      itemRow({ id: "old", collectionId: "late", createdAt: "2026-11-01T00:00:00Z" }),
      itemRow({ id: "new", collectionId: "late", createdAt: "2026-11-04T00:00:00Z" }),
      itemRow({ id: "removed", collectionId: "late", deletedAt: "2026-11-05T00:00:00Z" }),
      itemRow({ id: "in-deleted", collectionId: "gone" }),
      itemRow({ id: "orphan", collectionId: "missing" }),
    ];

    const grouped = groupCollections(collections, items);

    expect(grouped.map((collection) => collection.id)).toEqual(["tie-older", "tie-newer", "late"]);
    expect(grouped.map((collection) => collection.items.map((item) => item.id))).toEqual([[], [], ["new", "old"]]);
  });
});

describe("mosaicImages", () => {
  it("takes the four newest image URLs, skipping posts without one", () => {
    const items = [
      itemRow({ id: "1", imageUrl: null }),
      itemRow({ id: "2", imageUrl: "b" }),
      itemRow({ id: "3", imageUrl: "c" }),
      itemRow({ id: "4", imageUrl: "d" }),
      itemRow({ id: "5", imageUrl: "e" }),
      itemRow({ id: "6", imageUrl: "f" }),
    ];

    expect(mosaicImages(withItems(items))).toEqual(["b", "c", "d", "e"]);
  });

  it("pads with neutral cells", () => {
    expect(mosaicImages(withItems([itemRow({ imageUrl: "a" }), itemRow({ imageUrl: "b" })]))).toEqual([
      "a",
      "b",
      null,
      null,
    ]);
    expect(mosaicImages(withItems([]))).toEqual([null, null, null, null]);
  });
});

describe("post labels", () => {
  it.each([
    [{ kind: "x", url: "https://x.com/a/status/1", durationSeconds: 48 }, "X video"],
    [{ kind: "x", url: "https://x.com/a/status/1", durationSeconds: null }, "X post"],
    [{ kind: "youtube", url: "https://youtu.be/a", durationSeconds: null }, "YouTube"],
    [{ kind: "link", url: "https://www.theathletic.com/a", durationSeconds: null }, "theathletic.com"],
    [{ kind: "link", url: "not a url", durationSeconds: null }, "not a url"],
  ])("postSourceLabel(%o) is %p", (item, label) => {
    expect(postSourceLabel(item)).toBe(label);
  });

  it("postByline joins the author and source, or shows just the source", () => {
    expect(
      postByline({ author: "@BearsFilmRoom", kind: "x", url: "https://x.com/a/status/1", durationSeconds: 48 }),
    ).toBe("@BearsFilmRoom · X video");
    expect(postByline({ author: null, kind: "link", url: "https://example.com/a", durationSeconds: null })).toBe(
      "example.com",
    );
  });

  it.each([
    [{ kind: "youtube", durationSeconds: null }, true],
    [{ kind: "link", durationSeconds: 30 }, true],
    [{ kind: "x", durationSeconds: null }, false],
  ])("isVideo(%o) is %p", (item, video) => {
    expect(isVideo(item)).toBe(video);
  });

  it.each([
    [48, "0:48"],
    [192, "3:12"],
    [3725, "1:02:05"],
  ])("formatDuration(%p) is %p", (seconds, label) => {
    expect(formatDuration(seconds)).toBe(label);
  });

  it("counts and dates", () => {
    expect(savedCountLabel(14)).toBe("14 saved");
    expect(savedDate(new Date(2026, 10, 3, 12).toISOString())).toBe("Nov 3");
  });
});

describe("defaultCollectionId", () => {
  it("prefers the last used collection, then the newest, then none", () => {
    const collections = [{ id: "a" }, { id: "b" }];

    expect(defaultCollectionId(collections, "a")).toBe("a");
    expect(defaultCollectionId(collections, "gone")).toBe("b");
    expect(defaultCollectionId(collections, null)).toBe("b");
    expect(defaultCollectionId([], "a")).toBeNull();
  });
});
