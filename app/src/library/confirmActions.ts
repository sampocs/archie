import * as WebBrowser from "expo-web-browser";

import { deleteSource } from "@/db/actions";
import { db } from "@/db/client";
import { haptic } from "@/ui/haptics";
import { requestSync } from "@/sync/useSync";

import type { SourceRow } from "./join";

/**
 * Opens the confirmation link in the in-app browser sheet and, once it closes (whatever the result), deletes the
 * email: the owner has seen the page, so the card has done its job.
 */
export async function confirmSignup(source: Pick<SourceRow, "id" | "confirmUrl">): Promise<void> {
  if (!source.confirmUrl) return;

  haptic("light");
  await WebBrowser.openBrowserAsync(source.confirmUrl);
  dismissSignup(source.id);
}

/** Deletes a confirmation email without opening its link. */
export function dismissSignup(sourceId: string): void {
  deleteSource(db, sourceId);
  haptic("success");
  requestSync();
}
