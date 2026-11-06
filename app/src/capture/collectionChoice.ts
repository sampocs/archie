import { defaultCollectionId } from "@/collections/collections";
import type { SharedCollection } from "@/collections/sharedCollectionsFormat";

import type { CollectionPick } from "./types";

export const NEW_COLLECTION_LABEL = "New collection…";

/** The pick a collection save starts on: the last-used collection, else the newest, else a new one. */
export function defaultCollectionPick(collections: SharedCollection[], lastUsedId: string | null): CollectionPick {
  const id = defaultCollectionId(collections, lastUsedId);
  return id === null ? { kind: "new", name: "" } : { kind: "existing", id };
}

/** The chosen pick, unless it names a collection that no longer exists, in which case the default. */
export function resolveCollectionPick(
  chosen: CollectionPick | null,
  collections: SharedCollection[],
  lastUsedId: string | null,
): CollectionPick {
  const stillValid = chosen !== null && (chosen.kind === "new" || collections.some((entry) => entry.id === chosen.id));
  return stillValid ? chosen : defaultCollectionPick(collections, lastUsedId);
}

export function collectionPickLabel(pick: CollectionPick, collections: SharedCollection[]): string {
  if (pick.kind === "new") return pick.name.trim() || NEW_COLLECTION_LABEL;
  return collections.find((collection) => collection.id === pick.id)?.name ?? NEW_COLLECTION_LABEL;
}

/**
 * Whether Save is allowed. A new collection with no name is fine where the app can ask for it on Save, but the
 * share extension cannot prompt, so its name field must be filled first.
 */
export function canSaveToCollection(pick: CollectionPick | null, opts: { asksForName: boolean }): boolean {
  if (pick === null) return false;
  if (pick.kind === "existing") return true;
  return opts.asksForName || pick.name.trim() !== "";
}
