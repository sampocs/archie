import { cardRow, takeRow, takeVersionRow } from "@/review/testCards";

import {
  cleanState,
  earlierVersions,
  editorHint,
  editorStart,
  filterTakes,
  groupTakes,
  saveMakesVersion,
  shownBody,
  takeDate,
  takeFilterCounts,
  takeListMeta,
  takePageMeta,
  type TakeVersionRow,
  type TakeWithVersions,
} from "./takes";

const NOW = new Date(2026, 10, 5, 12);
const NOV_2 = "2026-11-02T15:00:00Z";

/** A live take with `count` versions (the last one current, made on Nov 2) and `cards` live cards. */
function takeWith(
  count: number,
  cards = 0,
  overrides: { id?: string; kind?: string; version?: Partial<TakeVersionRow> } = {},
): TakeWithVersions {
  const id = overrides.id ?? "k1";
  const versions = Array.from({ length: count }, (_, index) =>
    takeVersionRow({
      id: `${id}-v${index + 1}`,
      takeId: id,
      version: index + 1,
      createdAt: index === count - 1 ? NOV_2 : `2026-10-${String(10 + index).padStart(2, "0")}T15:00:00Z`,
      ...(index === count - 1 ? overrides.version : {}),
    }),
  );
  const cardRows = Array.from({ length: cards }, (_, index) =>
    cardRow({ id: `${id}-c${index}`, sourceId: null, takeId: id, kind: "take" }),
  );
  const take = takeRow({ id, kind: overrides.kind ?? "talking_point", currentVersion: count });
  return groupTakes([take], versions, cardRows)[0];
}

describe("saveMakesVersion", () => {
  const plain = takeVersionRow({ body: "Same.", rawBody: "Same.", cleaned: 0 });
  const cleaned = takeVersionRow({ body: "Cleaned.", rawBody: "raw", cleaned: 1 });

  it("makes a version on a first save or a changed body", () => {
    expect(saveMakesVersion(null, { body: "Anything.", clean: false })).toBe(true);
    expect(saveMakesVersion(plain, { body: "Changed.", clean: false })).toBe(true);
  });

  it("makes none for the same body, compared with the raw text while the cleanup runs", () => {
    expect(saveMakesVersion(plain, { body: "Same.", clean: false })).toBe(false);
    expect(saveMakesVersion(takeVersionRow({ body: null, rawBody: "raw", cleaned: 1 }), { body: "raw", clean: true })).toBe(
      false,
    );
  });

  it("makes one when Clean it up is switched on for a version that wasn't cleaned", () => {
    expect(saveMakesVersion(plain, { body: "Same.", clean: true })).toBe(true);
    expect(saveMakesVersion(cleaned, { body: "Cleaned.", clean: true })).toBe(false);
    expect(saveMakesVersion(cleaned, { body: "Cleaned.", clean: false })).toBe(false);
  });
});

describe("cleanState and shownBody", () => {
  it("reads the version's cleanup state", () => {
    expect(cleanState(takeVersionRow({ cleaned: 0 }))).toBe("none");
    expect(cleanState(takeVersionRow({ cleaned: 1, body: null }))).toBe("cleaning");
    expect(cleanState(takeVersionRow({ cleaned: 1, body: "Cleaned." }))).toBe("cleaned");
    expect(cleanState(takeVersionRow({ cleaned: 1, body: "raw", cleanFailed: 1 }))).toBe("failed");
  });

  it("shows the raw text while the body is null", () => {
    expect(shownBody(takeVersionRow({ body: null, rawBody: "raw" }))).toBe("raw");
    expect(shownBody(takeVersionRow({ body: "Cleaned.", rawBody: "raw" }))).toBe("Cleaned.");
  });
});

describe("groupTakes", () => {
  it("hides deleted takes and sorts each take's versions oldest first", () => {
    const grouped = groupTakes(
      [takeRow({ id: "k1", currentVersion: 2 }), takeRow({ id: "gone", deletedAt: NOV_2 })],
      [
        takeVersionRow({ id: "v2", version: 2 }),
        takeVersionRow({ id: "v1", version: 1 }),
        takeVersionRow({ id: "gone-v1", takeId: "gone" }),
      ],
      [],
    );

    expect(grouped.map((take) => take.id)).toEqual(["k1"]);
    expect(grouped[0].versions.map((version) => version.id)).toEqual(["v1", "v2"]);
    expect(grouped[0].current?.id).toBe("v2");
  });

  it("picks the version matching currentVersion, else the newest, else none", () => {
    const versions = [takeVersionRow({ id: "v1", version: 1 }), takeVersionRow({ id: "v2", version: 2 })];

    expect(groupTakes([takeRow({ currentVersion: 1 })], versions, [])[0].current?.id).toBe("v1");
    expect(groupTakes([takeRow({ currentVersion: 5 })], versions, [])[0].current?.id).toBe("v2");
    expect(groupTakes([takeRow({ currentVersion: 1 })], [], [])[0].current).toBeNull();
  });

  it("counts only the take's live cards", () => {
    const cards = [
      cardRow({ id: "c1", sourceId: null, takeId: "k1" }),
      cardRow({ id: "c2", sourceId: null, takeId: "k1", deletedAt: NOV_2 }),
      cardRow({ id: "c3", sourceId: null, takeId: "k2" }),
      cardRow({ id: "c4" }),
    ];

    expect(groupTakes([takeRow({})], [takeVersionRow({})], cards)[0].cardCount).toBe(1);
  });

  it("orders by the current version's date, so a rename doesn't move a take up", () => {
    const grouped = groupTakes(
      [
        takeRow({ id: "renamed", currentVersion: 1, updatedAt: "2026-11-05T15:00:00Z" }),
        takeRow({ id: "rewritten", currentVersion: 1, updatedAt: "2026-11-03T15:00:00Z" }),
      ],
      [
        takeVersionRow({ id: "a", takeId: "renamed", createdAt: "2026-11-01T15:00:00Z" }),
        takeVersionRow({ id: "b", takeId: "rewritten", createdAt: "2026-11-03T15:00:00Z" }),
      ],
      [],
    );

    expect(grouped.map((take) => take.id)).toEqual(["rewritten", "renamed"]);
  });
});

describe("dates and meta lines", () => {
  it("dates this year by day, earlier years by month", () => {
    expect(takeDate(NOV_2, NOW)).toBe("Nov 2");
    expect(takeDate(new Date(2024, 10, 3).toISOString(), NOW)).toBe("Nov 2024");
  });

  it("builds the Takes row's line", () => {
    expect(takeListMeta(takeWith(1), NOW)).toBe("Written Nov 2");
    expect(takeListMeta(takeWith(1, 2), NOW)).toBe("Written Nov 2 · 2 cards");
    expect(takeListMeta(takeWith(1, 1), NOW)).toBe("Written Nov 2 · 1 card");
    expect(takeListMeta(takeWith(3, 4), NOW)).toBe("Updated Nov 2 · 3 versions · 4 cards");
  });

  it("builds the take page's line", () => {
    expect(takePageMeta(takeWith(1), NOW)).toBe("Written Nov 2 · version 1");
    expect(takePageMeta(takeWith(3), NOW)).toBe("Updated Nov 2 · version 3");
  });
});

describe("earlierVersions", () => {
  it("lists every version but the current one, newest first", () => {
    expect(earlierVersions(takeWith(3)).map((version) => version.version)).toEqual([2, 1]);
  });

  it("still does after a restore copied version 1 as version 3", () => {
    const restored = takeWith(3, 0, { version: { body: "Body.", rawBody: "Body." } });
    expect(earlierVersions(restored).map((version) => version.version)).toEqual([2, 1]);
  });
});

describe("filterTakes and takeFilterCounts", () => {
  const list = [
    takeWith(1, 0, { id: "o1", kind: "opinion" }),
    takeWith(1, 0, { id: "t1" }),
    takeWith(1, 0, { id: "o2", kind: "opinion" }),
    takeWith(1, 0, { id: "t2" }),
    takeWith(1, 0, { id: "odd", kind: "manifesto" }),
  ];

  it("counts each kind, an unknown kind as a talking point", () => {
    expect(takeFilterCounts(list)).toEqual({ all: 5, opinion: 2, talking_point: 3 });
  });

  it("keeps only the chosen kind, in order", () => {
    expect(filterTakes(list, "opinion").map((take) => take.id)).toEqual(["o1", "o2"]);
    expect(filterTakes(list, "talking_point").map((take) => take.id)).toEqual(["t1", "t2", "odd"]);
    expect(filterTakes(list, "all")).toBe(list);
  });
});

describe("the editor", () => {
  it("hints which version saving makes", () => {
    expect(editorHint(null)).toBe("Saving makes version 1 and writes this take's cards.");
    expect(editorHint(takeWith(3))).toBe("Saving makes version 4 and rewrites this take's cards.");
  });

  it("opens empty, as a talking point, for a new take", () => {
    expect(editorStart(null)).toEqual({ kind: "talking_point", title: "", body: "", clean: false });
  });

  it("opens on what the page shows, with Clean it up as the take last had it", () => {
    const cleaned = takeWith(1, 0, { kind: "opinion", version: { body: "Cleaned.", rawBody: "raw", cleaned: 1 } });
    const cleaning = takeWith(1, 0, { version: { body: null, rawBody: "raw", cleaned: 1 } });
    const plain = takeWith(1, 0, { version: { body: "Plain.", rawBody: "Plain." } });

    expect(editorStart(cleaned)).toEqual({ kind: "opinion", title: "T", body: "Cleaned.", clean: true });
    expect(editorStart(cleaning)).toEqual({ kind: "talking_point", title: "T", body: "raw", clean: true });
    expect(editorStart(plain)).toEqual({ kind: "talking_point", title: "T", body: "Plain.", clean: false });
  });
});
