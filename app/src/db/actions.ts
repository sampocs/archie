import { randomUUID } from "expo-crypto";

import type { Intent, Reaction } from "@/capture/types";

import { eq } from "drizzle-orm";

import type { AppDb } from "./client";
import * as schema from "./schema";

const STATE_BY_INTENT: Record<Intent, string> = { finished: "consumed", queue: "queued" };

// The source row and its outbox entry commit together: a source without its outbox row would never sync.
export async function addSource(
  db: AppDb,
  input: { url: string; intent: Intent; reaction?: Reaction | null; note?: string | null; prepMe?: boolean },
): Promise<string> {
  const id = randomUUID();
  const now = new Date().toISOString();

  db.transaction((tx) => {
    tx.insert(schema.sources)
      .values({
        id,
        url: input.url,
        kind: "link",
        state: STATE_BY_INTENT[input.intent],
        intent: input.intent,
        reaction: input.reaction ?? null,
        note: input.note || null,
        prepMe: input.prepMe ? 1 : 0,
        createdAt: now,
        updatedAt: now,
      })
      .run();

    tx.insert(schema.outbox)
      .values({
        id: randomUUID(),
        type: "add_source",
        payload: JSON.stringify({
          id,
          url: input.url,
          intent: input.intent,
          // Unset options are omitted from the wire payload, not sent as null.
          ...(input.reaction ? { reaction: input.reaction } : {}),
          ...(input.note ? { note: input.note } : {}),
          ...(input.prepMe ? { prep_me: true } : {}),
        }),
        createdAt: now,
        status: "pending",
      })
      .run();
  });

  return id;
}

// Optimistically shows "Processing" while the retry action syncs; the server's pulled status replaces it.
export async function retrySource(db: AppDb, sourceId: string): Promise<void> {
  const now = new Date().toISOString();

  db.transaction((tx) => {
    tx.update(schema.sources)
      .set({ processing: "processing", processingError: null })
      .where(eq(schema.sources.id, sourceId))
      .run();

    tx.insert(schema.outbox)
      .values({
        id: randomUUID(),
        type: "retry_source",
        payload: JSON.stringify({ id: sourceId }),
        createdAt: now,
        status: "pending",
      })
      .run();
  });
}
