import { artifactEntries, cardEntries, originLabel, takeEntries } from "./versions";

const artifact = (version: number, isCurrent: number, origin: string, instruction: string | null = null) => ({
  id: `a${version}`,
  sourceId: "s1",
  kind: "primer",
  version,
  content: JSON.stringify({ markdown: `v${version}` }),
  isCurrent,
  createdAt: `2026-11-0${version}T00:00:00Z`,
  origin,
  instruction,
});

describe("version lists", () => {
  it("lists artifact versions newest first and marks the current one, even when it isn't the newest", () => {
    const entries = artifactEntries("primer", [
      artifact(1, 0, "archie"),
      artifact(2, 1, "chat_edit", "Drop the jargon"),
      artifact(3, 0, "archie"),
    ]);
    expect(entries.map((entry) => [entry.version, entry.current, entry.origin, entry.instruction])).toEqual([
      [3, false, "archie", null],
      [2, true, "chat_edit", "Drop the jargon"],
      [1, false, "archie", null],
    ]);
    expect(entries[1].content).toEqual({ markdown: "v2" });
  });

  it("gives a card with no history one current entry, and otherwise its rows", () => {
    const card = { id: "c1", question: "Q?", answer: "B.", version: 2, createdAt: "2026-11-01T00:00:00Z" };
    expect(cardEntries({ ...card, version: 1 }, [])).toEqual([
      {
        version: 1,
        createdAt: card.createdAt,
        origin: "archie",
        instruction: null,
        content: { question: "Q?", answer: "B." },
        current: true,
      },
    ]);
    const rows = [
      { id: "v1", cardId: "c1", version: 1, question: "Q?", answer: "A.", origin: "archie", instruction: null, createdAt: "x" },
      { id: "v2", cardId: "c1", version: 2, question: "Q?", answer: "B.", origin: "care", instruction: "Rates", createdAt: "y" },
    ];
    expect(cardEntries(card, rows).map((entry) => [entry.version, entry.current])).toEqual([
      [2, true],
      [1, false],
    ]);
  });

  it("marks a take's current version by its number and shows the raw text while cleaning", () => {
    const rows = [
      { id: "t1", takeId: "k", version: 1, body: null, rawBody: "raw", cleaned: 1, cleanFailed: 0, createdAt: "x", origin: "owner" },
      { id: "t2", takeId: "k", version: 2, body: "B", rawBody: "B", cleaned: 0, cleanFailed: 0, createdAt: "y", origin: "chat_edit" },
    ];
    const entries = takeEntries({ currentVersion: 2 }, rows);
    expect(entries.map((entry) => [entry.version, entry.current, entry.content])).toEqual([
      [2, true, { markdown: "B" }],
      [1, false, { markdown: "raw" }],
    ]);
  });

  it("labels each origin, and an unknown one as Archie", () => {
    expect(["archie", "owner", "chat_edit", "care", "restore", "later"].map(originLabel)).toEqual([
      "Archie",
      "You",
      "Edited in Ask",
      "Rewritten from your note",
      "Restored",
      "Archie",
    ]);
  });
});
