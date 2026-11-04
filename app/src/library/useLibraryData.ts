import { desc, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { joinLibrary, type LibraryData } from "./join";

/** Everything Today and Library read, live: non-deleted sources newest first, with their topics and primers. */
export function useLibraryData(): LibraryData {
  const { data: sources } = useLiveQuery(
    db.select().from(schema.sources).where(isNull(schema.sources.deletedAt)).orderBy(desc(schema.sources.createdAt)),
  );
  const { data: artifacts } = useLiveQuery(db.select().from(schema.artifacts).where(eq(schema.artifacts.isCurrent, 1)));
  const { data: topics } = useLiveQuery(db.select().from(schema.topics));
  const { data: topicPrimers } = useLiveQuery(
    db.select().from(schema.topicPrimers).where(eq(schema.topicPrimers.isCurrent, 1)),
  );

  return useMemo(
    () => joinLibrary({ sources, artifacts, topics, topicPrimers }),
    [sources, artifacts, topics, topicPrimers],
  );
}
