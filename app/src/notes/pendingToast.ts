import { useSyncExternalStore } from "react";

/**
 * The note whose Done was just tapped; the toast root waits for its cards to land, then clears it. `cardCount` is set
 * when the owner saved the cards in a chat, so the toast shows at once with the cards they kept. `message` is set for
 * a Done that makes no cards now ("Note done", "Cards saved for later"): the toast shows at once with that text.
 */
export type PendingRefreshToast = { sourceId: string; title: string; cardCount?: number; message?: string };

let pending: PendingRefreshToast | null = null;
const listeners = new Set<() => void>();

function publish(next: PendingRefreshToast | null): void {
  pending = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function setPendingRefreshToast(entry: PendingRefreshToast): void {
  publish(entry);
}

export function clearPendingRefreshToast(): void {
  publish(null);
}

export function usePendingRefreshToast(): PendingRefreshToast | null {
  return useSyncExternalStore(subscribe, () => pending);
}
