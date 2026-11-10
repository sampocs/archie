import { cardKicker, chatItemLine } from "./kicker";
import { cardRow, conversationRow, reviewData, sourceRow, takeRow } from "./testCards";

describe("cardKicker", () => {
  const data = reviewData([], { takes: [takeRow({ id: "k1", kind: "opinion" }), takeRow({ id: "k2" })] });
  const takeCard = (takeId: string) => cardRow({ sourceId: null, takeId, kind: "take" });

  it("reads This week · News for a quiz card", () => {
    expect(cardKicker(cardRow({ sourceId: null, briefId: "b1", kind: "quiz" }), data)).toEqual({
      label: "This week",
      suffix: "News",
      domain: null,
    });
  });

  it("reads Your take · <kind> in the kind's colour for a take card", () => {
    expect(cardKicker(takeCard("k1"), data)).toEqual({ label: "Your take", suffix: "Opinion", domain: "History" });
    expect(cardKicker(takeCard("k2"), data)).toEqual({ label: "Your take", suffix: "Talking point", domain: "Startups" });
    expect(cardKicker(takeCard("gone"), data)).toEqual({
      label: "Your take",
      suffix: "Talking point",
      domain: "Startups",
    });
  });

  it("reads From Ask in the about item's colour for a chat card, else Other", () => {
    const chatData = reviewData([], {
      conversations: [
        conversationRow({ id: "about-source", aboutKind: "source", aboutSourceId: "s1" }),
        conversationRow({ id: "general" }),
      ],
    });
    const chatCard = (conversationId: string) => cardRow({ sourceId: null, conversationId });

    expect(cardKicker(chatCard("about-source"), chatData)).toEqual({
      label: "From Ask",
      suffix: undefined,
      domain: "AI",
    });
    expect(cardKicker(chatCard("general"), chatData)).toEqual({ label: "From Ask", suffix: undefined, domain: null });
  });

  it("reads the kind in the source's domain colour for a source card", () => {
    expect(cardKicker(cardRow({}), data)).toEqual({ label: undefined, suffix: "Concept", domain: "AI" });
  });
});

describe("chatItemLine", () => {
  it("names a chat item's card by its item, to open it", () => {
    const data = reviewData([], { sources: [sourceRow({ id: "s1", kind: "chat", title: "JWT vs session tokens" })] });
    expect(chatItemLine(cardRow({}), data)).toEqual({ sourceId: "s1", title: "JWT vs session tokens", kind: "Chat" });
  });

  it("is null for any other source's card, and for a chat card from before chat items", () => {
    expect(chatItemLine(cardRow({}), reviewData([]))).toBeNull();
    expect(chatItemLine(cardRow({ sourceId: null, conversationId: "k1" }), reviewData([]))).toBeNull();
  });
});
