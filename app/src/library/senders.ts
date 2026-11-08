/** The words the phone shows for a newsletter from a sender the owner hasn't decided on: card, toasts, item page. */

import type { SenderStatus } from "@/db/actions";
import type * as schema from "@/db/schema";

type SourceRow = typeof schema.sources.$inferSelect;
export type PendingSenderSource = Pick<SourceRow, "sender" | "senderAddress" | "title">;

const UNKNOWN_SENDER = "Unknown";

export const SENDER_KICKER_SUFFIX = "New sender";

/** The sender's display name, else its address; "Unknown" when the email carried neither. */
export function senderLabel(source: PendingSenderSource): string {
  return source.sender?.trim() || source.senderAddress?.trim() || UNKNOWN_SENDER;
}

export function senderHeadline(source: PendingSenderSource): string {
  return `New sender: ${senderLabel(source)}`;
}

/** The card's second line: `{address} · {time}`, or just the time when the email had no address. */
export function senderFrom(source: PendingSenderSource, time: string): string {
  const address = source.senderAddress?.trim();
  return address ? `${address} · ${time}` : time;
}

/** The email's subject for the card's third line; null when there is none, so the line is left out. */
export function senderSubject(source: PendingSenderSource): string | null {
  return source.title?.trim() || null;
}

export function senderToast(source: PendingSenderSource, status: SenderStatus): string {
  return `${senderLabel(source)} ${status}`;
}

export function senderPrompt(source: PendingSenderSource): string {
  return `This email is from a new sender: ${senderLabel(source)}.`;
}

export const SENDER_EXPLANATION =
  "Allow lets Archie read and summarise it, and their future issues arrive as normal newsletters. Block deletes it, and Archie drops anything else they send.";
