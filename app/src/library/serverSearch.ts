import type { OwnerKind } from "@/ask/types";

/** Typing waits this long before asking the server, so a word costs one request, not one per letter. */
export const SEARCH_DEBOUNCE_MS = 300;

export type ServerSearchResult = {
  itemKind: "source" | "topic_primer" | "take";
  itemId: string;
  title: string;
  passage: string;
  ownerKind: OwnerKind;
  startSeconds: number | null;
};

export type SearchState = { status: "idle" | "loading" | "ready" | "failed"; results: ServerSearchResult[] };

const ITEM_KINDS = new Set(["source", "topic_primer", "take"]);

/** The `/search` body as rows; anything malformed is dropped. */
export function parseSearchResults(body: unknown): ServerSearchResult[] {
  const results = (body as { results?: unknown } | null)?.results;
  if (!Array.isArray(results)) return [];
  return results.flatMap((row) => {
    const item = row as Record<string, unknown>;
    if (!ITEM_KINDS.has(item.item_kind as string) || typeof item.item_id !== "string") return [];
    return [
      {
        itemKind: item.item_kind as ServerSearchResult["itemKind"],
        itemId: item.item_id,
        title: String(item.title ?? ""),
        passage: String(item.passage ?? ""),
        ownerKind: item.owner_kind as OwnerKind,
        startSeconds: typeof item.start_seconds === "number" ? item.start_seconds : null,
      },
    ];
  });
}

/**
 * Which results the list shows: the server's once they arrive online; meanwhile, offline, or after a failed request,
 * today's on-phone matching — with the offline line only when the server can't answer.
 */
export function searchView(input: {
  query: string;
  online: boolean;
  state: SearchState;
}): { mode: "server" | "local"; offlineLine: boolean } {
  if (!input.online || input.state.status === "failed") return { mode: "local", offlineLine: true };
  if (input.state.status === "ready") return { mode: "server", offlineLine: false };
  return { mode: "local", offlineLine: false };
}

/** Runs the last task given, `ms` after the last call. */
export function createDebouncer(ms: number): { run(task: () => void): void; cancel(): void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const cancel = () => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  };
  return {
    run(task) {
      cancel();
      timer = setTimeout(() => {
        timer = null;
        task();
      }, ms);
    },
    cancel,
  };
}
