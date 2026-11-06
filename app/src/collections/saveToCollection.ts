import { addCollectionItem, createCollection } from "@/db/actions";
import { db } from "@/db/client";
import type { CollectionPick } from "@/capture/types";

import { writeLastCollectionId } from "./sharedCollections";

/**
 * Drops a link into a collection (creating it when the pick is new) and remembers it for next time. It saves the
 * link into the collection only: no summary, no cards, nothing in the Library.
 */
export function saveToCollection(input: { url: string; pick: CollectionPick }): void {
  const { url, pick } = input;
  const collectionId = pick.kind === "existing" ? pick.id : createCollection(db, pick.name);
  addCollectionItem(db, { collectionId, url });
  void writeLastCollectionId(collectionId).catch(() => undefined);
}
