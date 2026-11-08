import { useSyncExternalStore } from "react";

/** The note whose Done was just tapped; the toast root waits for its cards to land, then clears it. */
export type PendingRefreshToast = { sourceId: string; title: string };

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
