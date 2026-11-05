import { parseMarkdown } from "@/ui/Markdown";

import { emailParagraphs } from "./emailText";

describe("emailParagraphs", () => {
  it("makes each single line break its own paragraph and keeps headings and lists", () => {
    const text = "# Blue tsunami\nDemocrats won the House.\r\nDisney cut jobs.\n\n\n- Binance hack\n- Rivian jumps";

    expect(parseMarkdown(emailParagraphs(text))).toEqual([
      { type: "heading", level: 1, spans: [{ text: "Blue tsunami" }] },
      { type: "paragraph", spans: [{ text: "Democrats won the House." }] },
      { type: "paragraph", spans: [{ text: "Disney cut jobs." }] },
      { type: "list", ordered: false, items: [[{ text: "Binance hack" }], [{ text: "Rivian jumps" }]] },
    ]);
  });
});
