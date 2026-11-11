import { randomUUID } from "expo-crypto";

import { apiFetch, NetworkError, UnauthorizedError } from "@/api/client";
import type { BookChoice, BookMatch } from "@/books/books";
import type { CaptureChoice, CollectionPick } from "@/capture/types";
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
      ...(choice.queuePrimer ? { queue_primer: true } : {}),
      ...(keepCapture ? { capture: { title: truncateTitle(capture.title), text: capture.text } } : {}),
    },
  };
}

/** A shared book: the same wire shape as `addBook` in db/actions.ts (thoughts only with Finished, and trimmed). */
export function buildAddBookAction(input: { match: BookMatch; choice: BookChoice }): OutboxEntry {
  const { match, choice } = input;
  const note = choice.state === "finished" ? choice.note.trim() : "";

  return {
    id: randomUUID(),
    type: "add_book",
    payload: {
      id: randomUUID(),
      url: match.url,
      title: truncateTitle(match.title),
      author: match.author,
      image_url: match.coverUrl,
      state: choice.state,
      ...(note ? { note } : {}),
    },
  };
}

/** What a collection share pushes: the post, preceded by its new collection when the pick is a new one. */
export function buildCollectionShareActions(input: { url: string; pick: CollectionPick }): {
  actions: OutboxEntry[];
  collectionId: string;
} {
  const { url, pick } = input;
  const collectionId = pick.kind === "existing" ? pick.id : randomUUID();
  const createActions: OutboxEntry[] =
    pick.kind === "new"
      ? [{ id: randomUUID(), type: "create_collection", payload: { id: collectionId, name: pick.name.trim() } }]
      : [];
  const addAction: OutboxEntry = {
    id: randomUUID(),
    type: "add_collection_item",
    payload: { id: randomUUID(), collection_id: collectionId, url },
  };

  return { actions: [...createActions, addAction], collectionId };
}

/** Posts the actions, in order, to /sync/push. Throws an Error carrying the server's reason when it rejects one. */
export async function submitShare(actions: OutboxEntry[], sessionKey: string | null): Promise<SubmitOutcome> {
  if (!sessionKey) return "signed-out";

  try {
    const response = (await withTimeout(
      apiFetch("/sync/push", { method: "POST", body: { actions }, sessionKey }),
    )) as { results: PushResult[] };
    return outcomeOf(actions.map((_, index) => response.results[index]));
  } catch (error) {
    if (error instanceof UnauthorizedError) return "signed-out";
    if (error instanceof NetworkError) return "offline";
    throw error;
  }
}

// Saved only when every action went through; otherwise the first failure's reason is what the sheet shows.
function outcomeOf(results: (PushResult | undefined)[]): SubmitOutcome {
  const failedIndex = results.findIndex((result) => result?.result !== "applied" && result?.result !== "duplicate");
  if (failedIndex === -1) return "saved";
  throw new Error(results[failedIndex]?.reason ?? "Archie couldn't accept this share");
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
  if (choice.intent === "collection") return `share?${[...params, ...collectionParams(choice.collection)].join("&")}`;
  if (choice.reaction) params.push(`reaction=${choice.reaction}`);
  if (choice.note) params.push(`note=${encodeShareParam(choice.note)}`);
  if (choice.queuePrimer) params.push("queue_primer=1");
  return `share?${params.join("&")}`;
}

/**
 * A book's fallback path (`archie://share?book=1&…`) when the extension can't reach the backend: the book's URL, title,
 * state and thoughts only (no author or cover). The route must run `decodeShareParam` on `url`, `title` and `note`.
 */
export function shareBookDeepLink(input: { match: BookMatch; choice: BookChoice }): string {
  const { match, choice } = input;
  const params = ["book=1", `url=${encodeShareParam(match.url)}`, `title=${encodeShareParam(match.title)}`];
  params.push(`state=${choice.state}`);
  const note = choice.state === "finished" ? choice.note.trim() : "";
  if (note) params.push(`note=${encodeShareParam(note)}`);
  return `share?${params.join("&")}`;
}

function collectionParams(pick: CollectionPick | null): string[] {
  if (pick?.kind === "existing") return [`collection=${pick.id}`];
  if (pick?.kind === "new") return [`collection_name=${encodeShareParam(pick.name.trim())}`];
  return [];
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
