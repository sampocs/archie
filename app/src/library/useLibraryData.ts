import { count, desc, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { joinLibrary, type LibraryData } from "./join";

/** Everything Today and Library read, live: non-deleted sources newest first, with their topics, primers and card counts. */
export function useLibraryData(): LibraryData {
  const { data: sources } = useLiveQuery(
    db.select().from(schema.sources).where(isNull(schema.sources.deletedAt)).orderBy(desc(schema.sources.createdAt)),
  );
  const { data: artifacts } = useLiveQuery(db.select().from(schema.artifacts).where(eq(schema.artifacts.isCurrent, 1)));
  const { data: topics } = useLiveQuery(db.select().from(schema.topics));
  const { data: topicPrimers } = useLiveQuery(
    db.select().from(schema.topicPrimers).where(eq(schema.topicPrimers.isCurrent, 1)),
  );
  const { data: cardRows } = useLiveQuery(
    db
      .select({ sourceId: schema.cards.sourceId, count: count() })
      .from(schema.cards)
      .where(isNull(schema.cards.deletedAt))
      .groupBy(schema.cards.sourceId),
  );

  return useMemo(() => {
    // Cards not tied to a source (from a topic or an ask) have no row to count under.
    const cardCounts = new Map<string, number>();
    for (const row of cardRows) if (row.sourceId !== null) cardCounts.set(row.sourceId, row.count);
    return joinLibrary({ sources, artifacts, topics, topicPrimers, cardCounts });
  }, [sources, artifacts, topics, topicPrimers, cardRows]);
}
