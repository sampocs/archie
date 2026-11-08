/** The words the phone shows for a signup-confirmation email: card headline, from line, toast and item-page text. */

import type * as schema from "@/db/schema";

type SourceRow = typeof schema.sources.$inferSelect;
export type ConfirmationSource = Pick<SourceRow, "confirmUrl" | "sender" | "title">;

const GMAIL_CONFIRM_PREFIX = "https://mail-settings.google.com/";
const GMAIL_ADDRESS_IN_TITLE = /Receive Mail from ([^\s()<>]+)/;
const GMAIL_FORWARDING = "Gmail forwarding";

/** Gmail's forwarding confirmation is told apart by where its link points. */
export function isGmailForwarding(source: ConfirmationSource): boolean {
  return source.confirmUrl?.startsWith(GMAIL_CONFIRM_PREFIX) ?? false;
}

export function confirmHeadline(source: ConfirmationSource): string {
  if (isGmailForwarding(source)) return `Confirm ${GMAIL_FORWARDING}`;
  return `Confirm your ${senderName(source) ?? "newsletter"} signup`;
}

/** The card's from line: the sender, or for Gmail "From you@gmail.com" (the address Gmail names in its subject). */
export function confirmFrom(source: ConfirmationSource): string {
  if (!isGmailForwarding(source)) return senderName(source) ?? "Newsletter";

  const address = GMAIL_ADDRESS_IN_TITLE.exec(source.title ?? "")?.[1] ?? senderName(source);
  return address ? `From ${address}` : "From Gmail";
}

export function confirmToast(source: ConfirmationSource): string {
  if (isGmailForwarding(source)) return `${GMAIL_FORWARDING} confirmed`;
  return `${senderName(source) ?? "Newsletter"} signup confirmed`;
}

export function confirmPrompt(source: ConfirmationSource): string {
  if (isGmailForwarding(source)) return `This email asks you to confirm ${GMAIL_FORWARDING}.`;
  return `This email asks you to confirm your ${senderName(source) ?? "newsletter"} signup.`;
}

export function confirmExplanation(source: ConfirmationSource): string {
  if (isGmailForwarding(source)) {
    return "Confirm opens Google's link. Once you're done, Archie deletes this email, and forwarded mail starts arriving as normal newsletters.";
  }

  const sender = senderName(source);
  const issues = sender ? `${sender}'s issues` : "its issues";
  return `Confirm opens the newsletter's link. Once you're done, Archie deletes this email, and ${issues} start arriving as normal newsletters.`;
}

function senderName(source: ConfirmationSource): string | null {
  const sender = source.sender?.trim();
  return sender ? sender : null;
}
