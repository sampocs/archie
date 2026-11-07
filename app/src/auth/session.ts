import * as AppleAuthentication from "expo-apple-authentication";
import * as SecureStore from "expo-secure-store";
import { useSyncExternalStore } from "react";

import { apiFetch } from "@/api/client";
import { clearSharedCollections } from "@/collections/sharedCollections";
import { db, seedSyncState } from "@/db/client";
import * as schema from "@/db/schema";

import { KEYCHAIN_KEY, LEGACY_OPTIONS, SHARED_OPTIONS } from "./keychain";
import { bumpSessionEpoch } from "./sessionEpoch";

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

// Moves an M1 key (stored in the app's own group) into the shared group so the share extension can read it and
// the owner doesn't sign in again. The legacy item is addressed by its explicit group, not "no group": an
// ungrouped query also matches the shared item, and deleting that would wipe the copy just made. A key already in
// the shared group is never overwritten; any legacy item left beside it is stale (e.g. a delete that failed earlier)
// and is removed so it can't be copied back after a sign-out.
export async function migrateSessionKeyToSharedGroup(): Promise<void> {
  const legacyKey = await SecureStore.getItemAsync(KEYCHAIN_KEY, LEGACY_OPTIONS);
  if (await SecureStore.getItemAsync(KEYCHAIN_KEY, SHARED_OPTIONS)) {
    if (legacyKey) await SecureStore.deleteItemAsync(KEYCHAIN_KEY, LEGACY_OPTIONS);
    return;
  }

  if (!legacyKey) return;

  await SecureStore.setItemAsync(KEYCHAIN_KEY, legacyKey, SHARED_OPTIONS);
  await SecureStore.deleteItemAsync(KEYCHAIN_KEY, LEGACY_OPTIONS);
}

// Read the keychain once at startup (after the migration); until it answers the app shows nothing rather than a
// flash of sign-in.
migrateSessionKeyToSharedGroup()
  .then(() => getSessionKey())
  .then((key) => setState(key ? { status: "signedIn", sessionKey: key } : { status: "signedOut", sessionKey: null }))
  .catch(() => setState({ status: "signedOut", sessionKey: null }));

export function useSession(): SessionState {
  return useSyncExternalStore(subscribe, () => state);
}

export async function getSessionKey(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYCHAIN_KEY, SHARED_OPTIONS);
}

export async function setSessionKey(key: string): Promise<void> {
  await SecureStore.setItemAsync(KEYCHAIN_KEY, key, SHARED_OPTIONS);
  setState({ status: "signedIn", sessionKey: key });
}

// Signing out revokes the server session (best effort, so it works offline) and wipes the local copy, so the next
// person to sign in on this device never sees it. The epoch is bumped first, synchronously, so sync runs already in
// flight stop writing before anything else happens. The wipe is one transaction covering every synced table, so the
// next account starts empty (a failure leaves the old data intact, never half-deleted), and the store flips to signedOut in `finally` because the Keychain key is already
// gone: a local-db failure must not leave the UI signedIn without a key.
export async function clearSession(): Promise<void> {
  bumpSessionEpoch();
  await revokeServerSession(state.sessionKey);
  try {
    await SecureStore.deleteItemAsync(KEYCHAIN_KEY, SHARED_OPTIONS);
    // A leftover legacy item would otherwise be migrated back into the shared group on the next launch.
    await SecureStore.deleteItemAsync(KEYCHAIN_KEY, LEGACY_OPTIONS);
    db.transaction((tx) => {
      tx.delete(schema.sources).run();
      tx.delete(schema.artifacts).run();
      tx.delete(schema.cards).run();
      tx.delete(schema.topics).run();
      tx.delete(schema.topicPrimers).run();
      tx.delete(schema.briefs).run();
      tx.delete(schema.collections).run();
      tx.delete(schema.collectionItems).run();
      tx.delete(schema.takes).run();
      tx.delete(schema.takeVersions).run();
      tx.delete(schema.conversations).run();
      tx.delete(schema.messages).run();
      // The review log goes with the account; review settings stay with the device.
      tx.delete(schema.reviews).run();
      tx.delete(schema.outbox).run();
      tx.delete(schema.syncState).run();
      seedSyncState();
    });
    // The share extension's copy of the collection names goes too, so the next account never sees them.
    await clearSharedCollections();
  } finally {
    setState({ status: "signedOut", sessionKey: null });
  }
}

// Sign-out never waits longer than this on the server: a slow or captive network must not hang it.
const REVOKE_TIMEOUT_MS = 3000;

// Failures are ignored on purpose: sign-out must work offline, and the key is discarded either way.
async function revokeServerSession(sessionKey: string | null): Promise<void> {
  if (!sessionKey) return;
  const revoke = apiFetch("/auth/logout", { method: "POST", sessionKey }).catch(() => undefined);
  const timeout = new Promise<void>((resolve) => setTimeout(resolve, REVOKE_TIMEOUT_MS));
  await Promise.race([revoke, timeout]);
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
