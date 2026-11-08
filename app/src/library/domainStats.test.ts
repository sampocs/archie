import { domainCards } from "./domainStats";
import type { LibraryData, LibrarySource, TopicPrimerRow, TopicRow } from "./join";
import { topicPrimerRow } from "./testRows";

const topic = (overrides: Partial<TopicRow>): TopicRow => ({
  id: "t1",
  domain: "Macro",
  name: "Rates",
  origin: "starter",
  removedAt: null,
  mergedIntoId: null,
  createdAt: "2026-11-01T00:00:00Z",
  updatedAt: "2026-11-01T00:00:00Z",
  primerRequestedAt: null,
  ...overrides,
});

const source = (overrides: Record<string, unknown>) => ({ state: "inbox", domain: "Macro", topicId: null, ...overrides }) as unknown as LibrarySource;

const data = (sources: LibrarySource[], topics: TopicRow[], topicPrimers: TopicPrimerRow[] = []): LibraryData => ({
  sources,
  confirmations: [],
  pendingSenders: [],
  topics,
  topicPrimers,
});

describe("domainCards", () => {
  it("splits a domain's items into done, queued and inbox", () => {
    const [card] = domainCards(
      data([source({ state: "consumed" }), source({ state: "queued" }), source({ state: "briefed" }), source({})], []),
    );
    expect([card.count, card.done, card.queued, card.inbox]).toEqual([4, 1, 1, 2]);
  });

  it("shows a domain with only a user topic, as an own chip with no items", () => {
    const cards = domainCards(data([], [topic({ id: "u", domain: "AI", name: "Agents", origin: "user" })]));
    expect(cards).toHaveLength(1);
    expect(cards[0].count).toBe(0);
    expect(cards[0].chips).toEqual([expect.objectContaining({ count: 0, own: true })]);
  });

  it("leaves out removed and merged topics, and starter topics without items", () => {
    const cards = domainCards(
      data(
        [source({ topicId: "a" }), source({ topicId: "b" })],
        [
          topic({ id: "a", removedAt: "2026-11-02T00:00:00Z" }),
          topic({ id: "b", mergedIntoId: "c" }),
          topic({ id: "d", name: "Empty starter" }),
        ],
      ),
    );
    expect(cards[0].chips).toEqual([]);
  });

  it("lists topics with items by count, then the user's own empty ones", () => {
    const [card] = domainCards(
      data(
        [source({ topicId: "a" }), source({ topicId: "b" }), source({ topicId: "b" })],
        [topic({ id: "a", name: "A" }), topic({ id: "b", name: "B" }), topic({ id: "c", name: "C", origin: "user" })],
      ),
    );
    expect(card.chips.map((chip) => [chip.topic.name, chip.count, chip.own])).toEqual([
      ["B", 2, false],
      ["A", 1, false],
      ["C", 0, true],
    ]);
  });

  it("orders cards by count, then domain order", () => {
    const cards = domainCards(
      data(
        [source({ domain: "AI" }), source({ domain: "Finance" }), source({ domain: "Macro" }), source({ domain: "Macro" })],
        [],
      ),
    );
    expect(cards.map((card) => card.domain)).toEqual(["Macro", "Finance", "AI"]);
  });

  it("marks a topic whose current primer is unopened, and only that one", () => {
    const [card] = domainCards(
      data(
        ["unread", "opened", "old", "none"].map((topicId) => source({ topicId })),
        [
          topic({ id: "unread", name: "Unread" }),
          topic({ id: "opened", name: "Opened" }),
          topic({ id: "old", name: "Old" }),
          topic({ id: "none", name: "None" }),
          topic({ id: "own", name: "Own", origin: "user" }),
        ],
        [
          topicPrimerRow({ id: "p1", topicId: "unread" }),
          topicPrimerRow({ id: "p2", topicId: "opened", openedAt: "2026-11-03T00:00:00Z" }),
          topicPrimerRow({ id: "p3", topicId: "old", isCurrent: 0 }),
          topicPrimerRow({ id: "p4", topicId: "own" }),
        ],
      ),
    );
    expect(Object.fromEntries(card.chips.map((chip) => [chip.topic.name, chip.unreadPrimer]))).toEqual({
      Unread: true,
      Opened: false,
      Old: false,
      None: false,
      Own: true,
    });
  });
});
