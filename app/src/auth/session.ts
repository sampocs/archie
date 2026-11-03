import * as AppleAuthentication from "expo-apple-authentication";
import * as SecureStore from "expo-secure-store";
import { useSyncExternalStore } from "react";

import { apiFetch } from "@/api/client";
import { db, seedSyncState } from "@/db/client";
import * as schema from "@/db/schema";

import { bumpSessionEpoch } from "./sessionEpoch";

const KEYCHAIN_KEY = "archie.session";

type SessionState = { status: "loading" | "signedOut" | "signedIn"; sessionKey: string | null };

// A tiny module-level store so `clearSession` (called from anywhere) updates every `useSession` subscriber.
let state: SessionState = { status: "loading", sessionKey: null };
const listeners = new Set<() => void>();

function setState(next: SessionState): void {
  state = next;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// Read the keychain once at startup; until it answers the app shows nothing rather than a flash of sign-in.
SecureStore.getItemAsync(KEYCHAIN_KEY)
  .then((key) => setState(key ? { status: "signedIn", sessionKey: key } : { status: "signedOut", sessionKey: null }))
  .catch(() => setState({ status: "signedOut", sessionKey: null }));

export function useSession(): SessionState {
  return useSyncExternalStore(subscribe, () => state);
}

export async function getSessionKey(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYCHAIN_KEY);
}

export async function setSessionKey(key: string): Promise<void> {
  await SecureStore.setItemAsync(KEYCHAIN_KEY, key);
  setState({ status: "signedIn", sessionKey: key });
}

// Signing out revokes the server session (best effort, so it works offline) and wipes the local copy, so the next
// person to sign in on this device never sees it. The epoch is bumped first, synchronously, so sync runs already in
// flight stop writing before anything else happens. The wipe is one transaction (a failure leaves the old data
// intact, never half-deleted), and the store flips to signedOut in `finally` because the Keychain key is already
// gone: a local-db failure must not leave the UI signedIn without a key.
export async function clearSession(): Promise<void> {
  bumpSessionEpoch();
  await revokeServerSession(state.sessionKey);
  try {
    await SecureStore.deleteItemAsync(KEYCHAIN_KEY);
    db.transaction((tx) => {
      tx.delete(schema.sources).run();
      tx.delete(schema.outbox).run();
      tx.delete(schema.syncState).run();
      seedSyncState();
    });
  } finally {
    setState({ status: "signedOut", sessionKey: null });
  }
}

// Failures are ignored on purpose: sign-out must work offline, and the key is discarded either way.
async function revokeServerSession(sessionKey: string | null): Promise<void> {
  if (!sessionKey) return;
  try {
    await apiFetch("/auth/logout", { method: "POST", sessionKey });
  } catch {
    // Unreachable or already invalid; nothing more to do.
  }
}

export async function signInWithApple(): Promise<void> {
  const credential = await AppleAuthentication.signInAsync({
    requestedScopes: [
      AppleAuthentication.AppleAuthenticationScope.FULL_NAME,
      AppleAuthentication.AppleAuthenticationScope.EMAIL,
    ],
  });
  if (!credential.identityToken) throw new Error("Apple returned no identity token");

  const response = (await apiFetch("/auth/apple", {
    method: "POST",
    body: { identity_token: credential.identityToken },
    sessionKey: null,
  })) as { session_key: string };
  await setSessionKey(response.session_key);
}
