import { isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useMemo } from "react";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { groupCollections, type CollectionWithItems } from "./collections";

/**
 * Every live collection with its posts, plus whether both live queries have answered: drizzle's `useLiveQuery`
 * returns `[]` on first render, so "no collection" only means "gone" once `loaded`.
 */
export function useCollectionsState(): { collections: CollectionWithItems[]; loaded: boolean } {
  const { data: collections, updatedAt: collectionsUpdatedAt } = useLiveQuery(
    db.select().from(schema.collections).where(isNull(schema.collections.deletedAt)),
  );
  const { data: items, updatedAt: itemsUpdatedAt } = useLiveQuery(
    db.select().from(schema.collectionItems).where(isNull(schema.collectionItems.deletedAt)),
  );

  const grouped = useMemo(() => groupCollections(collections, items), [collections, items]);

  return { collections: grouped, loaded: collectionsUpdatedAt !== undefined && itemsUpdatedAt !== undefined };
}

/** Every live collection with its posts, for Saved, the collection page and the add sheet. */
export function useCollectionsData(): CollectionWithItems[] {
  return useCollectionsState().collections;
}
