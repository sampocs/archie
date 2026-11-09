import { transcriptMarkdown } from "./chatTranscript";

const question = (text: string) => ({ role: "user", text, segments: null, status: "complete" });
const answer = (texts: string[], status = "complete") => ({
  role: "assistant",
  text: texts.join(" "),
  segments: JSON.stringify(texts.map((text, index) => ({ label: index === 0 ? "background" : "web", text, citations: [] }))),
  status,
});

describe("transcriptMarkdown", () => {
  it("writes each turn as You / Archie, an answer's sections as paragraphs", () => {
    expect(
      transcriptMarkdown([
        question(" JWTs vs sessions? "),
        answer(["A session token is a random ID.", "JWTs carry signed claims."]),
        question("Make cards"),
      ]),
    ).toBe(
      "**You:** JWTs vs sessions?\n\n**Archie:** A session token is a random ID.\n\nJWTs carry signed claims.\n\n**You:** Make cards",
    );
  });

  it("leaves out an answer that failed or is still streaming", () => {
    expect(transcriptMarkdown([question("Q?"), answer(["Half an"], "failed"), answer(["Still"], "streaming")])).toBe(
      "**You:** Q?",
    );
  });

  it("falls back to an answer's stored text when it has no segments", () => {
    expect(transcriptMarkdown([{ role: "assistant", text: "Plain answer", segments: null, status: "complete" }])).toBe(
      "**Archie:** Plain answer",
    );
  });
});
