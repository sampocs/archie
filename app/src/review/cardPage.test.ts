import { cardPills, cardSourceLink } from "./cardPage";
import {
  cardRow,
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

const labels = (pills: ReturnType<typeof cardPills>) => pills.map((pill) => pill.label);

describe("cardPills", () => {
  it("a new, unreviewed card shows only its due label", () => {
    const card = cardRow({});
    expect(labels(cardPills(card, reviewData([card]), NOW))).toEqual(["Due today"]);
  });

  it("counts reviews, names the latest grade and marks an edited card", () => {
    const card = reviewCard({ dueAt: dayAt(1), version: 2 });
    const data = reviewData([card], {
      reviews: [
        reviewRow({ id: "r1", grade: "missed", reviewedAt: dayAt(-3) }),
        reviewRow({ id: "r2", grade: "partly", reviewedAt: dayAt(-1) }),
        reviewRow({ id: "other", cardId: "c2", grade: "got_it", reviewedAt: dayAt(0) }),
      ],
    });

    const pills = cardPills(card, data, NOW);

    expect(labels(pills)).toEqual(["Due tomorrow", "Reviewed 2×", "Last: Partly", "Edited"]);
    expect(pills.find((pill) => pill.kind === "last")?.grade).toBe("partly");
  });

  it("a review that 'I actually knew it' replaced counts once, with the new grade", () => {
    const card = reviewCard({ dueAt: dayAt(4) });
    const data = reviewData([card], {
      reviews: [
        reviewRow({ id: "r1", grade: "missed", reviewedAt: dayAt(-1) }),
        reviewRow({ id: "r2", grade: "got_it", reviewedAt: dayAt(-1, 12, 1), replacesReviewId: "r1" }),
      ],
    });

    expect(labels(cardPills(card, data, NOW))).toEqual(["Due Mon", "Reviewed 1×", "Last: Got it"]);
  });

  it("a card of an unfinished source says After you finish", () => {
    const card = cardRow({});
    const data = reviewData([card], { sources: [sourceRow({ id: "s1", state: "inbox" })] });
    expect(labels(cardPills(card, data, NOW))).toEqual(["After you finish"]);
  });
});

describe("cardSourceLink", () => {
  it("opens a source by its title (its url without one)", () => {
    const card = cardRow({});
    const data = reviewData([card], { sources: [sourceRow({ id: "s1", title: null, url: "https://x.test/a" })] });
    expect(cardSourceLink(card, data)).toEqual({ title: "https://x.test/a", pathname: "/source/[id]", id: "s1" });
  });

  it("opens a take, and a topic primer's topic", () => {
    const takeCard = cardRow({ sourceId: null, takeId: "k1" });
    const primerCard = cardRow({ sourceId: null, topicPrimerId: "p1" });
    const data = reviewData([takeCard, primerCard], {
      takes: [takeRow({ id: "k1", title: "My take" })],
      topicPrimers: [topicPrimerRow({ id: "p1", topicId: "t1" })],
      topics: [topicRow({ id: "t1", name: "Derivatives" })],
    });

    expect(cardSourceLink(takeCard, data)).toEqual({ title: "My take", pathname: "/take/[id]", id: "k1" });
    expect(cardSourceLink(primerCard, data)).toEqual({ title: "Derivatives", pathname: "/topic/[id]", id: "t1" });
  });

  it("is hidden for a chat card and a gone source", () => {
    const chatCard = cardRow({ sourceId: null, conversationId: "chat1" });
    const goneCard = cardRow({ sourceId: "gone" });
    const data = reviewData([chatCard, goneCard]);
    expect(cardSourceLink(chatCard, data)).toBeNull();
    expect(cardSourceLink(goneCard, data)).toBeNull();
  });
});
