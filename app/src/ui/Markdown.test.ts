import { parseMarkdown } from "./Markdown";

describe("parseMarkdown", () => {
  it("parses headings by level", () => {
    expect(parseMarkdown("# One\n## Two\n### Three")).toEqual([
      { type: "heading", level: 1, spans: [{ text: "One" }] },
      { type: "heading", level: 2, spans: [{ text: "Two" }] },
      { type: "heading", level: 3, spans: [{ text: "Three" }] },
    ]);
  });

  it("joins consecutive lines into one paragraph and splits on blank lines", () => {
    expect(parseMarkdown("first line\nsecond line\n\nnext")).toEqual([
      { type: "paragraph", spans: [{ text: "first line second line" }] },
      { type: "paragraph", spans: [{ text: "next" }] },
    ]);
  });

  it("parses bold and italic spans inside a paragraph", () => {
    expect(parseMarkdown("a **bold** and *italic* end")).toEqual([
      {
        type: "paragraph",
        spans: [
          { text: "a " },
          { text: "bold", bold: true },
          { text: " and " },
          { text: "italic", italic: true },
          { text: " end" },
        ],
      },
    ]);
  });

  it("parses bullet lists with - and *, not mistaking * for italic", () => {
    expect(parseMarkdown("- one\n* two **b**")).toEqual([
      {
        type: "list",
        ordered: false,
        items: [[{ text: "one" }], [{ text: "two " }, { text: "b", bold: true }]],
      },
    ]);
  });

  it("parses numbered lists", () => {
    expect(parseMarkdown("1. a\n2. b")).toEqual([
      { type: "list", ordered: true, items: [[{ text: "a" }], [{ text: "b" }]] },
    ]);
  });

  it("ends a list at a heading or paragraph and keeps order across blocks", () => {
    const blocks = parseMarkdown("## H\ntext\n\n- x\n- y\nafter");
    expect(blocks.map((block) => block.type)).toEqual(["heading", "paragraph", "list", "paragraph"]);
  });

  it("returns no blocks for empty text", () => {
    expect(parseMarkdown("\n \n")).toEqual([]);
  });

  it("leaves unmatched asterisks as plain text", () => {
    expect(parseMarkdown("2 * 3 = 6")).toEqual([{ type: "paragraph", spans: [{ text: "2 * 3 = 6" }] }]);
  });
});
