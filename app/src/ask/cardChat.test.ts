import { conversationRow } from "@/review/testCards";

import { isFallbackIdTaken, latestCardChat } from "./cardChat";

describe("latestCardChat", () => {
  it("picks the card's live chat with the newest activity", () => {
    const chats = [
      conversationRow({ id: "old", aboutCardId: "c1", updatedAt: "2026-11-01T00:00:00Z" }),
      conversationRow({ id: "new", aboutCardId: "c1", updatedAt: "2026-11-03T00:00:00Z" }),
      conversationRow({ id: "deleted", aboutCardId: "c1", updatedAt: "2026-11-05T00:00:00Z", deletedAt: "x" }),
      conversationRow({ id: "other", aboutCardId: "c2", updatedAt: "2026-11-06T00:00:00Z" }),
    ];
    expect(latestCardChat(chats, "c1")?.id).toBe("new");
  });

  it("is null when the card has no live chat", () => {
    const chats = [conversationRow({ id: "deleted", aboutCardId: "c1", deletedAt: "x" }), conversationRow({})];
    expect(latestCardChat(chats, "c1")).toBeNull();
  });
});

describe("isFallbackIdTaken", () => {
  it("is taken when the card's chat with that id was deleted", () => {
    const chats = [conversationRow({ id: "mine", aboutCardId: "c1", deletedAt: "x" })];
    expect(isFallbackIdTaken(chats, "c1", "mine")).toBe(true);
  });

  it("is free when no chat of the card has that id", () => {
    const chats = [conversationRow({ id: "other", aboutCardId: "c1" }), conversationRow({ id: "mine", aboutCardId: "c2" })];
    expect(isFallbackIdTaken(chats, "c1", "mine")).toBe(false);
  });
});
