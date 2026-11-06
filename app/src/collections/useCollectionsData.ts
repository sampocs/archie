import { isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { groupCollections, type CollectionWithItems } from "./collections";

/** Every live collection with its posts, for Saved, the collection page and the add sheet. */
export function useCollectionsData(): CollectionWithItems[] {
  const { data: collections } = useLiveQuery(
    db.select().from(schema.collections).where(isNull(schema.collections.deletedAt)),
  );
  const { data: items } = useLiveQuery(
    db.select().from(schema.collectionItems).where(isNull(schema.collectionItems.deletedAt)),
  );

  return useMemo(() => groupCollections(collections, items), [collections, items]);
}
