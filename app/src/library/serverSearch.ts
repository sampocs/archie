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

export type SearchState = {
  status: "idle" | "loading" | "ready" | "failed";
  results: ServerSearchResult[];
  /** True when `results` came from a ready response, even while a newer request is loading. */
  fromServer: boolean;
};

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
 * Which results the list shows: the server's once a response has arrived online (kept while a newer request loads);
 * before the first response, offline, or after a failed request, on-phone matching alone — with the offline line only
 * when the server can't answer. In server mode the on-phone matches still follow the server's rows (see `localExtras`).
 */
export function searchView(input: {
  query: string;
  online: boolean;
  state: SearchState;
}): { mode: "server" | "local"; offlineLine: boolean } {
  if (!input.online || input.state.status === "failed") return { mode: "local", offlineLine: true };
  if (input.state.status === "ready" || (input.state.status === "loading" && input.state.fromServer)) {
    return { mode: "server", offlineLine: false };
  }
  return { mode: "local", offlineLine: false };
}

/**
 * The on-phone matches the server's rows don't already cover, in their given order. The server indexes only passage
 * text, so sources without text yet, notes and title-only matches reach the list only through the phone.
 */
export function localExtras(results: ServerSearchResult[], localMatchIds: string[]): string[] {
  const served = new Set(results.filter((result) => result.itemKind === "source").map((result) => result.itemId));
  return localMatchIds.filter((id) => !served.has(id));
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
