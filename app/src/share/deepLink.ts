import type { Intent, Reaction } from "@/capture/types";

import { decodeShareParam } from "./submit";

const INTENTS: readonly string[] = ["finished", "queue"] satisfies Intent[];
const REACTIONS: readonly string[] = ["easy", "mostly", "lost"] satisfies Reaction[];

export type ShareParams = { url?: string; intent?: string; reaction?: string; note?: string; queue_primer?: string };

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
