import { BOOK_STATES, type BookState } from "@/books/books";
import type { CollectionPick, Intent, Reaction } from "@/capture/types";

import { decodeShareParam } from "./submit";

const INTENTS: readonly string[] = ["finished", "queue"] satisfies Intent[];
const REACTIONS: readonly string[] = ["easy", "mostly", "lost"] satisfies Reaction[];

export type ShareParams = {
  url?: string;
  intent?: string;
  reaction?: string;
  note?: string;
  queue_primer?: string;
  collection?: string;
  collection_name?: string;
  book?: string;
  title?: string;
  state?: string;
};

export type SharedSource = {
  url: string;
  intent: Intent;
  reaction: Reaction | null;
  note: string | null;
  queuePrimer: boolean;
};

// Reads the params of archie://share?… (built by `shareDeepLink`). `url` and `note` arrive encoded with
// `encodeShareParam`, so they are decoded here. Returns null when there is nothing to save.
export function sharedSourceFromParams(params: ShareParams): SharedSource | null {
  const { url, intent, reaction, note, queue_primer: queuePrimer } = params;
  if (!url || !intent || !INTENTS.includes(intent)) return null;

  const isFinished = intent === "finished";
  return {
    url: decodeShareParam(url),
    intent: intent as Intent,
    // Reaction and note belong to finished only; the server rejects them on a queued source.
    reaction: isFinished && reaction && REACTIONS.includes(reaction) ? (reaction as Reaction) : null,
    note: isFinished && note ? decodeShareParam(note) : null,
    queuePrimer: !isFinished && queuePrimer === "1",
  };
}

export type SharedBook = { url: string; title: string; state: BookState; note: string | null };

/**
 * A book shared while the backend was unreachable (`book=1`, built by `shareBookDeepLink`): `url`, `title` and `note`
 * arrive encoded. Returns null when anything required is missing.
 */
export function sharedBookFromParams(params: ShareParams): SharedBook | null {
  const { book, url, title, state, note } = params;
  if (book !== "1" || !url || !title || !state || !(BOOK_STATES as readonly string[]).includes(state)) return null;

  return {
    url: decodeShareParam(url),
    title: decodeShareParam(title),
    state: state as BookState,
    // Thoughts belong to a finished book only.
    note: state === "finished" && note ? decodeShareParam(note) : null,
  };
}

/** A link to save into a collection (`intent=collection`): an existing collection's id, or a new one's name. */
export function sharedCollectionItemFromParams(params: ShareParams): { url: string; pick: CollectionPick } | null {
  const { url, intent, collection, collection_name: collectionName } = params;
  if (!url || intent !== "collection") return null;

  const name = collectionName ? decodeShareParam(collectionName).trim() : "";
  if (collection && !name) return { url: decodeShareParam(url), pick: { kind: "existing", id: collection } };
  if (name && !collection) return { url: decodeShareParam(url), pick: { kind: "new", name } };
  return null;
}
