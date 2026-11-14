/** A collection as the share extension needs it: just enough to list and pick it. */
export type SharedCollection = { id: string; name: string };

export function encodeSharedCollections(list: SharedCollection[]): string {
  return JSON.stringify(list.map(({ id, name }) => ({ id, name })));
}

/**
 * The list after the share sheet made a collection: it goes last, where a new collection's tile lands, so the next
 * share can pick it before the app has synced and rewritten the list.
 */
export function withSharedCollection(list: SharedCollection[], added: SharedCollection): SharedCollection[] {
  return list.some(({ id }) => id === added.id) ? list : [...list, added];
}

// The Keychain item may be missing, from an older build, or half-written; anything unreadable is "no collections".
export function parseSharedCollections(raw: string | null): SharedCollection[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(
    (entry): entry is SharedCollection =>
      typeof entry === "object" && entry !== null && typeof entry.id === "string" && typeof entry.name === "string",
  );
}
