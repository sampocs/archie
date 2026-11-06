/** A collection as the share extension needs it: just enough to list and pick it. */
export type SharedCollection = { id: string; name: string };

export function encodeSharedCollections(list: SharedCollection[]): string {
  return JSON.stringify(list.map(({ id, name }) => ({ id, name })));
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
