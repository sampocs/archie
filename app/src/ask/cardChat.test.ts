import { conversationRow } from "@/review/testCards";

import { latestCardChat } from "./cardChat";

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
