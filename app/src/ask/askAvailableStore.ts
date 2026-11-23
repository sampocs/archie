// One `/me` answer per session key, shared by every `useAskAvailable` consumer: whether the owner's keys pay for this
// account's Ask doesn't change while signed in. An unknown key (never answered, or the fetch failed offline) reads null.
const answers = new Map<string, boolean>();
const inFlight = new Set<string>();
const listeners = new Set<() => void>();

function publish(): void {
  listeners.forEach((listener) => listener());
}

export function subscribeAskAvailable(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** true / false once `/me` answered for this key; null while unknown. */
export function getAskAvailable(sessionKey: string | null): boolean | null {
  if (!sessionKey) return null;
  return answers.get(sessionKey) ?? null;
}

/**
 * Fetches `/me` when this key is still unknown and no fetch for it is running, so callers can invoke it on every
 * mount and every return to online. A failure leaves the key unknown for the next call to retry.
 */
export async function loadAskAvailable(sessionKey: string, fetchWhitelisted: () => Promise<boolean>): Promise<void> {
  if (answers.has(sessionKey) || inFlight.has(sessionKey)) return;

  inFlight.add(sessionKey);
  try {
    answers.set(sessionKey, await fetchWhitelisted());
    publish();
  } catch {
    // Offline or the server is down: stay unknown; the screens treat that as available and the next online retry asks again.
  } finally {
    inFlight.delete(sessionKey);
  }
}

/** Test only: forget every answer and running fetch. */
export function resetAskAvailableForTests(): void {
  answers.clear();
  inFlight.clear();
  publish();
}
