/** The user's newsletter address from a `/me` response, or null when it is missing or malformed. */
export function newsletterAddressFrom(me: unknown): string | null {
  if (typeof me !== "object" || me === null) return null;
  const address = (me as { ingest_address?: unknown }).ingest_address;
  if (typeof address !== "string" || !address.includes("@")) return null;
  return address;
}
