import { eq } from "drizzle-orm";

import { createDbSyncStore } from "@/sync/transport";

import { deleteConversation } from "./actions";
import type { AppDb } from "./client";
import * as schema from "./schema";
import { makeTestDb } from "./testDb";

jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));

const conversation = (overrides: Record<string, unknown> = {}) => ({
  id: "chat1",
  title: "How does the Fed create money?",
  about_kind: null,
  about_source_id: null,
  about_topic_primer_id: null,
  about_take_id: null,
  created_at: "2026-11-06T10:00:00Z",
  updated_at: "2026-11-06T10:00:00Z",
  deleted_at: null,
  change_seq: 3,
  ...overrides,
});
const message = (overrides: Record<string, unknown> = {}) => ({
  id: "m2",
  conversation_id: "chat1",
  role: "assistant",
  text: "Reserves.",
  segments: [{ label: "background", text: "Reserves.", citations: [] }],
  web_search: false,
  status: "complete",
  created_at: "2026-11-06T10:00:05Z",
  change_seq: 4,
  ...overrides,
});
const page = (rows: Record<string, unknown[]>, position: number) => ({
  rows: { sources: [], artifacts: [], cards: [], ...rows },
  position,
  more: false,
});
const chat = (db: AppDb) => db.select().from(schema.conversations).where(eq(schema.conversations.id, "chat1")).get();

describe("chats on the phone", () => {
  it("a pull stores conversations, messages (segments as JSON) and chat cards", async () => {
    const db = makeTestDb();
    const store = createDbSyncStore(db);

    await store.applyPage(
      page(
        {
          conversations: [conversation()],
          messages: [message()],
          cards: [
            {
              id: "c1", source_id: null, kind: "concept", question: "Q?", answer: "A.",
              created_at: "2026-11-06T10:01:00Z", deleted_at: null, change_seq: 5,
              conversation_id: "chat1", message_id: "m2",
            },
          ],
        },
        5,
      ) as never,
    );

    expect(chat(db)).toMatchObject({ title: "How does the Fed create money?", deletedAt: null });
    const [stored] = db.select().from(schema.messages).all();
    expect(stored).toMatchObject({ conversationId: "chat1", role: "assistant", webSearch: 0, status: "complete" });
    expect(JSON.parse(stored.segments!)).toEqual(message().segments);
    expect(db.select().from(schema.cards).get()).toMatchObject({ conversationId: "chat1", messageId: "m2" });
  });

  it("deleteConversation hides the chat at once and queues delete_conversation; an older pull doesn't undo it", async () => {
    const db = makeTestDb();
    const store = createDbSyncStore(db);
    await store.applyPage(page({ conversations: [conversation()] }, 3) as never);

    deleteConversation(db, "chat1");
    await store.applyPage(page({ conversations: [conversation({ change_seq: 6 })] }, 6) as never);

    expect(chat(db)?.deletedAt).not.toBeNull();
    const [entry] = db.select().from(schema.outbox).all();
    expect([entry.type, JSON.parse(entry.payload)]).toEqual(["delete_conversation", { id: "chat1" }]);
  });

  it("a rejected delete_conversation rewinds so the next pull restores the chat", async () => {
    const db = makeTestDb();
    const store = createDbSyncStore(db);
    await store.applyPage(page({ conversations: [conversation()] }, 3) as never);
    deleteConversation(db, "chat1");
    const entry = db.select().from(schema.outbox).get()!;

    await store.rejectAction(entry.id, "conversation not found");

    expect(await store.getPosition()).toBe(0);
  });
});
