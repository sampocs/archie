import { parseSummary } from "./summaryContent";

// Shape copied from a summary artifact the worker wrote for a transcribed podcast (trimmed).
const STORED = JSON.stringify({
  tags: ["odd news"],
  cards: [],
  topic: "Odd news",
  domain: "Other",
  summary: {
    gist: "This UPI Odd News Minute covers two light stories.",
    numbers: [{ fact: "The alligator was about three feet long.", timestamp: "00:00" }],
    key_ideas: [{ idea: "A baby alligator walked into a bagel shop.", timestamp: "00:00" }],
  },
  concepts: [],
  is_educational: false,
});

test("reads the gist, key ideas and numbers from under the stored analysis's summary", () => {
  const summary = parseSummary(STORED);

  expect(summary.gist).toBe("This UPI Odd News Minute covers two light stories.");
  expect(summary.key_ideas).toEqual([{ idea: "A baby alligator walked into a bagel shop.", timestamp: "00:00" }]);
  expect(summary.numbers).toHaveLength(1);
});

test("carries a note write-up's top-level sources, and leaves them off when there are none", () => {
  const sources = [{ url: "https://example.com/guide", title: "A Guide" }];
  const withSources = parseSummary(JSON.stringify({ summary: { gist: "g", key_ideas: [], numbers: [] }, sources }));

  expect(withSources.sources).toEqual(sources);
  expect(parseSummary(STORED).sources).toBeUndefined();
});
