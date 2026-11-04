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
