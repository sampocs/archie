import { originLabel } from "@/edits/versions";

import { takeDate, type CleanState, type TakeVersionRow } from "./takes";

/**
 * Whether to say "Cleaned up from your dictation": only over text that really was cleaned. A restored version
 * whose cleanup never finished stores its raw text as the body with `cleaned` set, and must not claim it.
 */
export function showsOrigin(
  state: CleanState,
  version: Pick<TakeVersionRow, "body" | "rawBody">,
): boolean {
  return state === "cleaned" && version.body !== null && version.body !== version.rawBody;
}

/** The version viewer's kicker: "Version 2 · Nov 2", plus how it was made when it wasn't the owner's own save. */
export function versionKicker(
  version: Pick<TakeVersionRow, "version" | "createdAt"> & { origin?: string },
  now: Date,
): string {
  const base = `Version ${version.version} · ${takeDate(version.createdAt, now)}`;
  return version.origin && version.origin !== "owner" ? `${base} · ${originLabel(version.origin)}` : base;
}
