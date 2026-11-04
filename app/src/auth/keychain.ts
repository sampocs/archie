import * as SecureStore from "expo-secure-store";

export const KEYCHAIN_KEY = "archie.session";

// The session key lives in a Keychain access group both the app and the share extension are entitled to
// (`keychain-access-groups` = `$(AppIdentifierPrefix)com.sampocs.archie.shared`, see plugins/withSharedKeychain.js).
// expo-secure-store takes the resolved value, so the team prefix is spelled out here.
export const SHARED_KEYCHAIN_GROUP = "3W3H65F89G.com.sampocs.archie.shared";

// Where M1 builds stored the key: the app's own identifier group, which only the main app can read.
export const LEGACY_KEYCHAIN_GROUP = "3W3H65F89G.com.sampocs.archie";

export const SHARED_OPTIONS: SecureStore.SecureStoreOptions = { accessGroup: SHARED_KEYCHAIN_GROUP };
export const LEGACY_OPTIONS: SecureStore.SecureStoreOptions = { accessGroup: LEGACY_KEYCHAIN_GROUP };

// What the share extension uses: it never writes the key, and never touches the database.
export async function readSharedSessionKey(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYCHAIN_KEY, SHARED_OPTIONS);
}
