import { editLines, parseContent, summaryAsMarkdown, type SummaryShape } from "./content";

const SUMMARY: SummaryShape = {
  gist: "Index funds beat most stock pickers.",
  key_ideas: [
    { timestamp: null, idea: "They track an index." },
    { timestamp: "12:30", idea: "Low fees compound." },
  ],
  numbers: [],
};

describe("editLines", () => {
  it("lays a summary out as its sections, leaving out an empty one", () => {
    expect(editLines("summary", SUMMARY)).toEqual([
      "Gist",
      "Index funds beat most stock pickers.",
      "Key ideas",
      "• They track an index.",
      "• Low fees compound.",
    ]);
  });

  it("splits markdown into its non-blank lines and a card into question and answer", () => {
    expect(editLines("primer", { markdown: "## Rates\n\nThe Fed sets them.  \n\n- Short ones\n" })).toEqual([
      "## Rates",
      "The Fed sets them.",
      "- Short ones",
    ]);
    expect(editLines("card", { question: "What?", answer: "That.", detail: "" })).toEqual(["Question: What?", "Answer: That."]);
    expect(editLines("card", { question: "What?", answer: "That.", detail: "Because.\n \nSo." })).toEqual([
      "Question: What?",
      "Answer: That.",
      "Detail:",
      "Because.",
      "So.",
    ]);
    expect(editLines("take", null)).toEqual([]);
  });
});

describe("parseContent", () => {
  it("accepts each kind's shape and rejects anything else", () => {
    expect(parseContent("summary", SUMMARY)).toEqual(SUMMARY);
    expect(parseContent("summary", { gist: "x" })).toBeNull();
    expect(parseContent("take", { markdown: "Body" })).toEqual({ markdown: "Body" });
    expect(parseContent("topic_primer", { text: "Body" })).toBeNull();
    expect(parseContent("card", { question: "Q?", answer: "A." })).toEqual({ question: "Q?", answer: "A.", detail: "" });
    expect(parseContent("card", { question: "Q?", answer: "A.", detail: "Why." })).toEqual({
      question: "Q?",
      answer: "A.",
      detail: "Why.",
    });
    expect(parseContent("card", "Q?")).toBeNull();
  });
});

it("renders a summary as markdown for the version preview", () => {
  expect(summaryAsMarkdown(SUMMARY)).toBe(
    "Index funds beat most stock pickers.\n\n## Key ideas\n\n1. They track an index.\n2. Low fees compound.",
  );
});
