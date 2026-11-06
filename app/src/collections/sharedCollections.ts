import * as SecureStore from "expo-secure-store";

import { SHARED_OPTIONS } from "@/auth/keychain";

import { encodeSharedCollections, parseSharedCollections, type SharedCollection } from "./sharedCollectionsFormat";

// Both items live in the Keychain group the share extension already reads the session key from (there is no App
// Group). The app alone writes the list, mirroring its database; both write the last-used id.
export const SHARED_COLLECTIONS_KEY = "archie.collections";
export const LAST_COLLECTION_KEY = "archie.lastCollection";

export async function writeSharedCollections(list: SharedCollection[]): Promise<void> {
  await SecureStore.setItemAsync(SHARED_COLLECTIONS_KEY, encodeSharedCollections(list), SHARED_OPTIONS);
}

export async function readSharedCollections(): Promise<SharedCollection[]> {
  return parseSharedCollections(await SecureStore.getItemAsync(SHARED_COLLECTIONS_KEY, SHARED_OPTIONS));
}

export async function readLastCollectionId(): Promise<string | null> {
  return SecureStore.getItemAsync(LAST_COLLECTION_KEY, SHARED_OPTIONS);
}

export async function writeLastCollectionId(id: string): Promise<void> {
  await SecureStore.setItemAsync(LAST_COLLECTION_KEY, id, SHARED_OPTIONS);
}

/** Sign-out: the next account must not see this one's collection names in the share sheet. */
export async function clearSharedCollections(): Promise<void> {
  await SecureStore.deleteItemAsync(SHARED_COLLECTIONS_KEY, SHARED_OPTIONS);
  await SecureStore.deleteItemAsync(LAST_COLLECTION_KEY, SHARED_OPTIONS);
}
