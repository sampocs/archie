import { matchesQuery, searchText } from "./search";
import { sourceRow, topicRow } from "./testRows";

const source = sourceRow({
  url: "https://example.com/zebra-crossing",
  title: "Odd Lots: What's really going on in repo",
  sender: "Morning Brew",
  domain: "Macro",
  topic: topicRow({ name: "Fed & monetary policy" }),
  summary: {
    gist: "Repo markets are where banks borrow overnight.",
    key_ideas: [{ idea: "The standing facility caps rates.", timestamp: null }],
    numbers: [],
  },
});

const matches = (query: string): boolean => matchesQuery(searchText(source), query);

describe("search", () => {
  it.each([
    ["title", "odd lots"],
    ["sender", "morning brew"],
    ["domain", "macro"],
    ["topic name", "monetary"],
    ["gist", "overnight"],
    ["key idea", "standing facility"],
  ])("matches on %s", (_, query) => {
    expect(matches(query)).toBe(true);
  });

  it("ignores case", () => {
    expect(matches("REPO Overnight")).toBe(true);
  });

  it("needs every term", () => {
    expect(matches("repo bitcoin")).toBe(false);
  });

  it("matches everything on an empty query", () => {
    expect(matches("   ")).toBe(true);
  });

  it("does not search the URL", () => {
    expect(matches("zebra")).toBe(false);
  });

  it("copes with a source that has only a URL", () => {
    expect(matchesQuery(searchText(sourceRow({ title: null })), "anything")).toBe(false);
  });
});
