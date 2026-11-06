import { domainFavorites, favoriteDomains, favoriteMeta } from "./favorites";
import { sourceRow } from "./testRows";

const star = (day: number) => new Date(2026, 10, day, 12).toISOString();

const sources = [
  sourceRow({ id: "a1", title: "A1", domain: "AI", favoritedAt: star(1), createdAt: "2026-11-09T00:00:00Z" }),
  sourceRow({ id: "a2", title: "A2", domain: "AI", favoritedAt: star(3), createdAt: "2026-11-01T00:00:00Z" }),
  sourceRow({ id: "a3", title: null, url: "https://example.com/untitled", domain: "AI", favoritedAt: star(2) }),
  sourceRow({ id: "c1", title: "C1", domain: "Crypto", favoritedAt: star(1) }),
  sourceRow({ id: "o1", title: "O1", domain: null, favoritedAt: star(1) }),
  sourceRow({ id: "m1", title: "M1", domain: "Macro", favoritedAt: null }),
];

describe("favoriteDomains", () => {
  it("is empty with no starred sources", () => {
    expect(favoriteDomains([sourceRow({ domain: "AI" })])).toEqual([]);
  });

  it("groups stars by domain, biggest first, ties in DOMAINS order, hiding unstarred domains", () => {
    expect(favoriteDomains(sources).map((group) => [group.domain, group.count])).toEqual([
      ["AI", 3],
      ["Crypto", 1],
      ["Other", 1],
    ]);
  });

  it("previews the two newest-starred titles, falling back to the URL", () => {
    const [ai] = favoriteDomains(sources);
    expect(ai.newestTitles).toEqual(["A2", "https://example.com/untitled"]);
  });
});

describe("domainFavorites", () => {
  it("returns only that domain's stars, newest star first", () => {
    expect(domainFavorites(sources, "AI").map((source) => source.id)).toEqual(["a2", "a3", "a1"]);
  });

  it("puts a domain-less source under Other", () => {
    expect(domainFavorites(sources, "Other").map((source) => source.id)).toEqual(["o1"]);
  });
});

describe("favoriteMeta", () => {
  it("reads kind and star date", () => {
    expect(favoriteMeta({ kind: "x", favoritedAt: new Date(2026, 10, 3, 12).toISOString() })).toBe("X post · starred Nov 3");
  });
});
