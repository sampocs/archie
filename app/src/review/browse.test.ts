import {
  asBrowseMode,
  browseItems,
  browseTopics,
  cardListOf,
  cardListTargetOf,
  cardOriginLabel,
  itemTitle,
  missedCards,
  missedTag,
  reviewStreak,
  searchCards,
  shufflePick,
} from "./browse";
import { buildSession } from "./session";
import {
  cardRow,
  conversationRow,
  dayAt,
  NOW,
  reviewCard,
  reviewData,
  reviewRow,
  sourceRow,
  takeRow,
  topicPrimerRow,
  topicRow,
} from "./testCards";
import type { ReviewGrade } from "./types";

describe("asBrowseMode", () => {
  it("keeps a stored mode and falls back to Topics", () => {
    expect(asBrowseMode("missed")).toBe("missed");
    expect(asBrowseMode("items")).toBe("items");
    expect(asBrowseMode("bogus")).toBe("topics");
    expect(asBrowseMode(null)).toBe("topics");
  });
});

describe("browseTopics", () => {
  it("counts each live topic's reviewable and due cards, busiest first, then by name", () => {
    const data = reviewData(
      [
        cardRow({ id: "a1", sourceId: "sa" }),
        reviewCard({ id: "b1", sourceId: "sb", dueAt: dayAt(-1) }),
        reviewCard({ id: "b2", sourceId: "sb", dueAt: dayAt(3) }),
        reviewCard({ id: "c1", sourceId: "sc", dueAt: dayAt(2) }),
        cardRow({ id: "unreviewable", sourceId: "sd" }),
        cardRow({ id: "removed", sourceId: "se" }),
        cardRow({ id: "deleted", sourceId: "sa", deletedAt: dayAt(-1) }),
        cardRow({ id: "primer-card", sourceId: null, topicPrimerId: "pc", kind: "foundation" }),
      ],
      {
        sources: [
          sourceRow({ id: "sa", state: "consumed", topicId: "ta" }),
          sourceRow({ id: "sb", state: "consumed", topicId: "tb" }),
          sourceRow({ id: "sc", state: "consumed", topicId: "tc" }),
          sourceRow({ id: "sd", state: "inbox", topicId: "td" }),
          sourceRow({ id: "se", state: "consumed", topicId: "te" }),
        ],
        topicPrimers: [topicPrimerRow({ id: "pc", topicId: "tc", openedAt: dayAt(-2) })],
        topics: [
          topicRow({ id: "tc", name: "Chips" }),
          topicRow({ id: "ta", name: "Agents" }),
          topicRow({ id: "tb", name: "Batteries" }),
          topicRow({ id: "td", name: "Drones" }),
          topicRow({ id: "te", name: "Energy", removedAt: dayAt(-1) }),
        ],
      },
    );

    expect(browseTopics(data, NOW).map(({ topic, count, due }) => [topic.name, count, due])).toEqual([
      ["Batteries", 2, 1],
      ["Chips", 2, 1],
      ["Agents", 1, 1],
    ]);
  });
});

describe("browseItems", () => {
  it("lists sources and takes with reviewable cards, latest review or card first", () => {
    const data = reviewData(
      [
        // s1: made long ago, reviewed yesterday.
        reviewCard({ id: "s1-a", sourceId: "s1", createdAt: dayAt(-20), lastReviewAt: dayAt(-1), dueAt: dayAt(4) }),
        cardRow({ id: "s1-b", sourceId: "s1", createdAt: dayAt(-20) }),
        // k1: a card made two days ago, never reviewed.
        cardRow({ id: "k1-a", sourceId: null, takeId: "k1", kind: "take", createdAt: dayAt(-2) }),
        // s2: a card made this morning.
        reviewCard({ id: "s2-a", sourceId: "s2", createdAt: dayAt(0, 8), lastReviewAt: null, dueAt: dayAt(1) }),
        cardRow({ id: "not-yet", sourceId: "s3", createdAt: dayAt(0, 11) }),
        cardRow({ id: "chat-card", sourceId: null, conversationId: "chat1", createdAt: dayAt(0, 11) }),
      ],
      {
        sources: [
          sourceRow({ id: "s1", state: "consumed", title: "Fed minutes" }),
          sourceRow({ id: "s2", state: "consumed", title: null, url: "https://example.com/untitled" }),
          sourceRow({ id: "s3", state: "inbox" }),
        ],
        takes: [takeRow({ id: "k1", title: "On rates" })],
      },
    );

    const rows = browseItems(data, NOW);
    expect(rows.map((row) => [row.kind, itemTitle(row), row.count, row.due])).toEqual([
      ["source", "https://example.com/untitled", 1, 0],
      ["source", "Fed minutes", 2, 1],
      ["take", "On rates", 1, 1],
    ]);
  });
});

describe("missedCards and missedTag", () => {
  const review = (id: string, cardId: string, grade: ReviewGrade, daysAgo: number, replaces: string | null = null) =>
    reviewRow({ id, cardId, grade, reviewedAt: dayAt(-daysAgo), replacesReviewId: replaces });
  const cards = ["twice", "once-recent", "once-older", "partly", "recovered", "old", "knew-it", "half"].map((id) =>
    reviewCard({ id, dueAt: dayAt(1) }),
  );
  const data = reviewData([...cards, cardRow({ id: "gone", deletedAt: dayAt(-1) })], {
    reviews: [
      review("r1", "twice", "missed", 10),
      review("r2", "twice", "missed", 5),
      review("r3", "once-recent", "missed", 1),
      review("r4", "once-older", "got_it", 9),
      review("r5", "once-older", "missed", 3),
      review("r6", "partly", "partly", 2),
      review("r7", "recovered", "missed", 4),
      review("r8", "recovered", "got_it", 2),
      // Missed 40 days ago only: outside the window.
      review("r9", "old", "missed", 40),
      // "I actually knew it" replaced the miss.
      review("r10", "knew-it", "missed", 2),
      review("r11", "knew-it", "got_it", 2, "r10"),
      // Two partlys weigh as much as one miss; the more recent one ranks first.
      review("r12", "half", "partly", 6),
      review("r13", "half", "partly", 2),
      review("r14", "gone", "missed", 1),
    ],
  });

  it("keeps cards whose latest review in 30 days missed, worst first, then most recent", () => {
    expect(missedCards(data, NOW).map(({ card }) => card.id)).toEqual([
      "twice",
      "once-recent",
      "half",
      "once-older",
      "partly",
    ]);
  });

  it("tags misses by count, and a card only ever partly as partly", () => {
    const tags = new Map(missedCards(data, NOW).map((entry) => [entry.card.id, missedTag(entry)]));
    expect(Object.fromEntries(tags)).toEqual({
      twice: "missed 2×",
      "once-recent": "missed",
      half: "partly",
      "once-older": "missed",
      partly: "partly",
    });
  });

  it("is empty with no reviews", () => {
    expect(missedCards(reviewData(cards), NOW)).toEqual([]);
  });

  it("missed session: the same cards in the same order, each due by its own date", () => {
    const session = buildSession(data, "missed", null, NOW, null);
    expect(session.map(({ card }) => card.id)).toEqual(["twice", "once-recent", "half", "once-older", "partly"]);
    expect(session.every(({ wasDue }) => !wasDue)).toBe(true);
  });
});

describe("searchCards", () => {
  const cards = [
    cardRow({ id: "q", question: "What is the Federal Funds rate?", answer: "An overnight rate." }),
    cardRow({ id: "a", question: "What does QT do?", answer: "Shrinks the FED balance sheet." }),
    cardRow({ id: "none", question: "What is a B-tree?", answer: "A balanced tree." }),
  ];

  it("matches question or answer, ignoring case and surrounding spaces", () => {
    expect(searchCards(cards, "  fed ").map((card) => card.id)).toEqual(["q", "a"]);
    expect(searchCards(cards, "OVERNIGHT").map((card) => card.id)).toEqual(["q"]);
    expect(searchCards(cards, "zebra")).toEqual([]);
  });

  it("finds nothing for a blank query", () => {
    expect(searchCards(cards, "   ")).toEqual([]);
  });
});

describe("reviewStreak", () => {
  const on = (...days: [number, number][]) => days.map(([day, hour]) => ({ reviewedAt: dayAt(day, hour) }));

  it("counts consecutive local days ending today", () => {
    expect(reviewStreak(on([0, 8], [0, 9], [-1, 23], [-2, 0]), NOW)).toBe(3);
  });

  it("still counts a streak through yesterday before today's first review", () => {
    expect(reviewStreak(on([-1, 7], [-2, 7], [-3, 7], [-4, 7]), NOW)).toBe(4);
  });

  it("stops at a gap", () => {
    expect(reviewStreak(on([0, 7], [-1, 7], [-3, 7], [-4, 7]), NOW)).toBe(2);
  });

  it("is zero when the last review was two days ago, or never", () => {
    expect(reviewStreak(on([-2, 7], [-3, 7]), NOW)).toBe(0);
    expect(reviewStreak([], NOW)).toBe(0);
  });
});

describe("shufflePick and shuffle sessions", () => {
  it("picks up to the count, without repeats, in the order the random draws give", () => {
    const items = ["a", "b", "c", "d"];
    // Each draw takes the last item still in the pool, which the previous swap refilled: d, then a, then b.
    expect(shufflePick(items, 3, () => 0.999)).toEqual(["d", "a", "b"]);
    // Always the first remaining item: the original order.
    expect(shufflePick(items, 10, () => 0)).toEqual(["a", "b", "c", "d"]);
    expect(items).toEqual(["a", "b", "c", "d"]);
  });

  it("shuffle session: at most 10 live reviewable cards, none others", () => {
    const live = Array.from({ length: 12 }, (_, index) => reviewCard({ id: `live-${index}`, dueAt: dayAt(5) }));
    const data = reviewData([
      ...live,
      cardRow({ id: "deleted", deletedAt: dayAt(-1) }),
      cardRow({ id: "unfinished", sourceId: "s9" }),
      cardRow({ id: "quiz", sourceId: null, briefId: "b1", kind: "quiz", expiresAt: dayAt(3) }),
    ]);

    const session = buildSession(data, "shuffle", null, NOW, null, () => 0.999);
    const ids = session.map(({ card }) => card.id);
    expect(ids).toHaveLength(10);
    expect(new Set(ids).size).toBe(10);
    expect(ids.every((id) => id.startsWith("live-"))).toBe(true);
    expect(ids[0]).toBe("live-11");
    // Not due yet, so like an ahead review none counts as due.
    expect(session.every(({ wasDue }) => !wasDue)).toBe(true);
  });

  it("shuffle session: empty with nothing reviewable", () => {
    const data = reviewData([cardRow({ id: "unfinished", sourceId: "s9" })]);
    expect(buildSession(data, "shuffle", null, NOW, null)).toEqual([]);
  });
});

describe("cardListTargetOf and cardListOf", () => {
  const data = reviewData(
    [
      cardRow({ id: "src", sourceId: "s1" }),
      cardRow({ id: "primer", sourceId: null, topicPrimerId: "p1", kind: "foundation" }),
      cardRow({ id: "take", sourceId: null, takeId: "k1", kind: "take" }),
      cardRow({ id: "deleted", sourceId: "s1", deletedAt: dayAt(-1) }),
    ],
    { takes: [takeRow({ id: "k1", title: "On rates" })] },
  );

  it("reads the first target given", () => {
    expect(cardListTargetOf({ topic: "t1", source: "s1" })).toEqual({ kind: "topic", id: "t1" });
    expect(cardListTargetOf({ source: "s1" })).toEqual({ kind: "source", id: "s1" });
    expect(cardListTargetOf({ take: "k1" })).toEqual({ kind: "take", id: "k1" });
    expect(cardListTargetOf({})).toBeNull();
  });

  it("names the topic or item and lists its live cards", () => {
    const ids = (target: Parameters<typeof cardListOf>[1]) => {
      const list = cardListOf(data, target);
      return list ? [list.title, list.cards.map((card) => card.id)] : null;
    };
    expect(ids({ kind: "topic", id: "t1" })).toEqual(["Agents", ["src", "primer"]]);
    expect(ids({ kind: "source", id: "s1" })).toEqual(["A", ["src"]]);
    expect(ids({ kind: "take", id: "k1" })).toEqual(["On rates", ["take"]]);
    expect(ids({ kind: "take", id: "missing" })).toBeNull();
  });
});

describe("cardOriginLabel", () => {
  const data = reviewData([], {
    sources: [
      sourceRow({ id: "s1", state: "consumed", title: "How the Fed creates money" }),
      sourceRow({ id: "s2", state: "consumed", title: null }),
    ],
    takes: [takeRow({ id: "k1", title: "On rates" })],
    conversations: [conversationRow({ id: "chat1", title: "JWTs" })],
  });

  it.each([
    ["a source card", cardRow({ sourceId: "s1" }), "From How the Fed creates money"],
    ["an untitled source's card", cardRow({ sourceId: "s2", kind: "mechanism" }), "Mechanism"],
    ["a take card", cardRow({ sourceId: null, takeId: "k1", kind: "take" }), "From On rates"],
    ["a chat card", cardRow({ sourceId: null, conversationId: "chat1" }), "From JWTs"],
    ["a topic's foundation card", cardRow({ sourceId: null, topicPrimerId: "p1", kind: "foundation" }), "Foundation"],
  ])("%s → %p", (_, card, label) => {
    expect(cardOriginLabel(card, data)).toBe(label);
  });
});
