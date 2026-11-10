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

  it("keeps a link's address on its span", () => {
    expect(parseMarkdown("See [the guide](https://example.com/g) now")).toEqual([
      {
        type: "paragraph",
        spans: [{ text: "See " }, { text: "the guide", href: "https://example.com/g" }, { text: " now" }],
      },
    ]);
  });

  it("caps deeper headings at level 3", () => {
    expect(parseMarkdown("#### Deep")).toEqual([{ type: "heading", level: 3, spans: [{ text: "Deep" }] }]);
  });

  it("parses task items and + bullets as lists", () => {
    expect(parseMarkdown("- [ ] todo\n- [x] done")).toEqual([
      { type: "list", ordered: false, items: [[{ text: "☐ todo" }], [{ text: "☑ done" }]] },
    ]);
    expect(parseMarkdown("+ plus")).toEqual([{ type: "list", ordered: false, items: [[{ text: "plus" }]] }]);
  });

  it("drops highlight and strikethrough markers", () => {
    expect(parseMarkdown("==hi== and ~gone~")).toEqual([{ type: "paragraph", spans: [{ text: "hi and gone" }] }]);
  });

  it("leaves a Bear tag as a paragraph", () => {
    expect(parseMarkdown("#crypto/staking")).toEqual([{ type: "paragraph", spans: [{ text: "#crypto/staking" }] }]);
  });

  it("parses a pipe table: header, then rows, skipping the rule under the header", () => {
    const text = "| | Session | JWT |\n|---|:---:|---|\n| Revoke | Delete row | **Wait** for expiry |\n| Scale | Shared store | Stateless |";
    expect(parseMarkdown(text)).toEqual([
      {
        type: "table",
        header: [[], [{ text: "Session" }], [{ text: "JWT" }]],
        rows: [
          [[{ text: "Revoke" }], [{ text: "Delete row" }], [{ text: "Wait", bold: true }, { text: " for expiry" }]],
          [[{ text: "Scale" }], [{ text: "Shared store" }], [{ text: "Stateless" }]],
        ],
      },
    ]);
  });

  it("parses a table written without the outer pipes", () => {
    expect(parseMarkdown("a | b\n---|---\n1 | 2")).toEqual([
      { type: "table", header: [[{ text: "a" }], [{ text: "b" }]], rows: [[[{ text: "1" }], [{ text: "2" }]]] },
    ]);
  });

  it("ends a table at the first line that isn't a row, and starts a new one after", () => {
    const blocks = parseMarkdown("| a | b |\n| 1 | 2 |\nAfter the table\n\n| c |\n| 3 |");
    expect(blocks.map((block) => block.type)).toEqual(["table", "paragraph", "table"]);
    expect(blocks[2]).toEqual({ type: "table", header: [[{ text: "c" }]], rows: [[[{ text: "3" }]]] });
  });

  it("leaves a line with a pipe inside it as a paragraph", () => {
    expect(parseMarkdown("cats | dogs")).toEqual([{ type: "paragraph", spans: [{ text: "cats | dogs" }] }]);
  });
});
