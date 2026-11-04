import { randomUUID } from "expo-crypto";

import { apiFetch, NetworkError, UnauthorizedError } from "@/api/client";
import type { CaptureChoice } from "@/capture/types";
import type { OutboxEntry, PushResult } from "@/sync/engine";

export type SubmitOutcome = "saved" | "offline" | "signed-out";

type PageCapture = { title: string | null; text: string };

// The server rejects longer values, and a rejected action would lose the whole share; the URL alone still works.
const MAX_CAPTURE_TEXT_CHARS = 400_000;
const MAX_CAPTURE_TITLE_CHARS = 500;

// Cuts by code point, so an emoji at the boundary is dropped whole instead of leaving half a surrogate pair.
function truncateTitle(title: string | null | undefined): string | null {
  if (title == null) return null;
  return Array.from(title).slice(0, MAX_CAPTURE_TITLE_CHARS).join("");
}

// A hung request must read as offline, so the sheet offers Open Archie instead of spinning forever.
const SUBMIT_TIMEOUT_MS = 15_000;

type ShareInput = { url: string; choice: CaptureChoice; capture: PageCapture | null };

export function buildShareAction(input: ShareInput): OutboxEntry {
  const { url, choice, capture } = input;
  const keepCapture = capture !== null && capture.text.length <= MAX_CAPTURE_TEXT_CHARS;

  return {
    id: randomUUID(),
    type: "add_source",
    // Same wire shape as `addSource` in db/actions.ts: unset options are omitted, not sent as null.
    payload: {
      id: randomUUID(),
      url,
      intent: choice.intent,
      ...(choice.reaction ? { reaction: choice.reaction } : {}),
      ...(choice.note ? { note: choice.note } : {}),
      ...(choice.prepMe ? { prep_me: true } : {}),
      ...(keepCapture ? { capture: { title: truncateTitle(capture.title), text: capture.text } } : {}),
    },
  };
}

/** Posts the action to /sync/push. Throws an Error carrying the server's reason when it rejects the action. */
export async function submitShare(action: OutboxEntry, sessionKey: string | null): Promise<SubmitOutcome> {
  if (!sessionKey) return "signed-out";

  try {
    const response = (await withTimeout(
      apiFetch("/sync/push", { method: "POST", body: { actions: [action] }, sessionKey }),
    )) as { results: PushResult[] };
    return outcomeOf(response.results[0]);
  } catch (error) {
    if (error instanceof UnauthorizedError) return "signed-out";
    if (error instanceof NetworkError) return "offline";
    throw error;
  }
}

function outcomeOf(result: PushResult | undefined): SubmitOutcome {
  if (result?.result === "applied" || result?.result === "duplicate") return "saved";
  throw new Error(result?.reason ?? "Archie couldn't accept this share");
}

function withTimeout<T>(request: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new NetworkError("push timed out")), SUBMIT_TIMEOUT_MS);
  });
  return Promise.race([request, timeout]).finally(() => clearTimeout(timer));
}

/**
 * The path `openHostApp` takes (`archie://share?...`): what Task 8's share route reads, with no page capture.
 * Values go through `encodeShareParam`, so the route must run `decodeShareParam` on `url` and `note`.
 */
export function shareDeepLink(input: { url: string; choice: CaptureChoice }): string {
  const { url, choice } = input;
  const params = [`url=${encodeShareParam(url)}`];
  if (choice.intent) params.push(`intent=${choice.intent}`);
  if (choice.reaction) params.push(`reaction=${choice.reaction}`);
  if (choice.note) params.push(`note=${encodeShareParam(choice.note)}`);
  if (choice.prepMe) params.push("prep_me=1");
  return `share?${params.join("&")}`;
}

// The extension's native side splits the path on "&" and "=" and then percent-encodes each value again, so a
// plain value with "&" breaks the query and an already-encoded one arrives double-encoded. "%" is swapped for "~"
// (which nothing touches) after literal "~" is escaped, so the value arrives exactly as written. Same trick as
// the share-extension spike.
export function encodeShareParam(value: string): string {
  return encodeURIComponent(value).replace(/~/g, "%7E").replace(/%/g, "~");
}

export function decodeShareParam(encoded: string): string {
  return decodeURIComponent(encoded.replace(/~/g, "%"));
}
