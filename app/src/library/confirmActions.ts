import * as WebBrowser from "expo-web-browser";

import { deleteSource, judgeSender } from "@/db/actions";
import { db } from "@/db/client";
import { haptic } from "@/ui/haptics";
import { requestSync } from "@/sync/useSync";

import { isGmailForwarding } from "./confirmations";
import type { SourceRow } from "./join";

let confirmInFlight = false;

/**
 * Opens the confirmation link in the in-app browser sheet and, once it closes (whatever the result), deletes the
 * email: the owner has seen the page, so the card has done its job. Confirming also allows the newsletter's sender
 * (so its issues aren't held as a new sender), except for Gmail forwarding, whose sender is Google, not a newsletter.
 * Resolves true only when the email was deleted.
 */
export async function confirmSignup(source: Pick<SourceRow, "id" | "confirmUrl" | "sender" | "title">): Promise<boolean> {
  if (!source.confirmUrl || confirmInFlight) return false;

  confirmInFlight = true;
  haptic("light");
  try {
    await WebBrowser.openBrowserAsync(source.confirmUrl);
  } catch {
    // The sheet never opened (e.g. another browser is presenting), so the owner hasn't seen the page: keep the email.
    return false;
  } finally {
    confirmInFlight = false;
  }

  if (!isGmailForwarding(source)) judgeSender(db, source.id, "allowed");
  dismissSignup(source.id);
  return true;
}

/** Deletes a confirmation email without opening its link. */
export function dismissSignup(sourceId: string): void {
  deleteSource(db, sourceId);
  haptic("success");
  requestSync();
}
