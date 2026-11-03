import { randomUUID } from "expo-crypto";

import type { AppDb } from "./client";
import * as schema from "./schema";

export type Intent = "finished" | "queue";

const STATE_BY_INTENT: Record<Intent, string> = { finished: "consumed", queue: "queued" };

// The source row and its outbox entry commit together: a source without its outbox row would never sync.
export async function addSource(db: AppDb, input: { url: string; intent: Intent }): Promise<string> {
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
        createdAt: now,
        updatedAt: now,
      })
      .run();

    tx.insert(schema.outbox)
      .values({
        id: randomUUID(),
        type: "add_source",
        payload: JSON.stringify({ id, url: input.url, intent: input.intent }),
        createdAt: now,
        status: "pending",
      })
      .run();
  });

  return id;
}
