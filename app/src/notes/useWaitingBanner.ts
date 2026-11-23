import { inArray } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useEffect, useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { droppedWaiting, waitingBanner, type WaitingBanner } from "./waiting";

/**
 * The banner, read live from the waiting table and the notes. Rows that no longer count (deleted note, cards turned
 * off) are deleted as they are read, so the table does not grow.
 */
export function useWaitingBanner(): WaitingBanner | null {
  const { data: rows, updatedAt: rowsLoadedAt } = useLiveQuery(db.select().from(schema.waitingNoteCards));
  const { data: sources, updatedAt: sourcesLoadedAt } = useLiveQuery(
    db
      .select({
        id: schema.sources.id,
        title: schema.sources.title,
        url: schema.sources.url,
        kind: schema.sources.kind,
        deletedAt: schema.sources.deletedAt,
        cardsOff: schema.sources.cardsOff,
      })
      .from(schema.sources),
  );
  // Live queries start empty; pruning against an unloaded notes list would drop every row.
  const loaded = rowsLoadedAt !== undefined && sourcesLoadedAt !== undefined;

  useEffect(() => {
    if (!loaded) return;
    const dropped = droppedWaiting(rows, sources);
    if (dropped.length === 0) return;
    db.delete(schema.waitingNoteCards).where(inArray(schema.waitingNoteCards.sourceId, dropped)).run();
  }, [loaded, rows, sources]);

  return useMemo(() => waitingBanner(rows, sources), [rows, sources]);
}
