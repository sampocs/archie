import { eq } from "drizzle-orm";

import * as schema from "@/db/schema";
import { makeTestDb } from "@/db/testDb";

import { confirmSignup } from "./confirmActions";

// expo-crypto and the browser are native modules; the database is the app's real migrated schema.
jest.mock("expo-crypto", () => ({ randomUUID: () => require("crypto").randomUUID() }));
jest.mock("expo-web-browser", () => ({ openBrowserAsync: jest.fn().mockResolvedValue({ type: "dismiss" }) }));
jest.mock("@/db/client", () => ({ db: require("@/db/testDb").makeTestDb() }));
jest.mock("@/sync/useSync", () => ({ requestSync: jest.fn() }));
jest.mock("@/ui/haptics", () => ({ haptic: jest.fn() }));

const { db } = require("@/db/client") as { db: ReturnType<typeof makeTestDb> };
const WebBrowser = require("expo-web-browser") as { openBrowserAsync: jest.Mock };

const GMAIL_LINK = "https://mail-settings.google.com/mail/vf-abc";

const seed = (id: string, overrides: Partial<typeof schema.sources.$inferInsert>) =>
  db
    .insert(schema.sources)
    .values({
      id, url: `newsletter:${id}`, kind: "newsletter", state: "inbox", intent: "queue", processing: "ready",
      createdAt: "2026-11-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z", ...overrides,
    })
    .run();
const row = (id: string) => db.select().from(schema.sources).where(eq(schema.sources.id, id)).get();
const queued = () => db.select().from(schema.outbox).all().map((entry) => ({ type: entry.type, payload: JSON.parse(entry.payload) }));

beforeEach(() => {
  db.delete(schema.outbox).run();
  db.delete(schema.sources).run();
  WebBrowser.openBrowserAsync.mockResolvedValue({ type: "dismiss" });
});

describe("confirmSignup", () => {
  it("allows the sender (un-pending its waiting issue) before deleting the confirmation", async () => {
    seed("confirm", { confirmUrl: "https://example.com/confirm", sender: "Example Weekly" });
    seed("issue", { sender: "Example Weekly", senderPending: true });

    expect(await confirmSignup({ ...row("confirm")! })).toBe(true);

    expect(row("issue")).toMatchObject({ senderPending: false, processing: "pending" });
    expect(row("confirm")?.deletedAt).not.toBeNull();
    expect(queued()).toEqual([
      { type: "set_sender_status", payload: { source_id: "confirm", status: "allowed" } },
      { type: "delete_source", payload: { id: "confirm" } },
    ]);
  });

  it("does not allow anyone for Gmail forwarding, but still deletes the email", async () => {
    seed("gmail", { confirmUrl: GMAIL_LINK, sender: "Gmail Team" });
    seed("issue", { sender: "Gmail Team", senderPending: true });

    expect(await confirmSignup({ ...row("gmail")! })).toBe(true);

    expect(row("issue")).toMatchObject({ senderPending: true });
    expect(queued()).toEqual([{ type: "delete_source", payload: { id: "gmail" } }]);
  });

  it("neither allows nor deletes when the sheet never opens", async () => {
    seed("confirm", { confirmUrl: "https://example.com/confirm", sender: "Example Weekly" });
    WebBrowser.openBrowserAsync.mockRejectedValue(new Error("busy"));

    expect(await confirmSignup({ ...row("confirm")! })).toBe(false);

    expect(row("confirm")?.deletedAt).toBeNull();
    expect(queued()).toEqual([]);
  });
});
