import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { Text as NativeText } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";

import { apiFetch, UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { SignOutContext } from "@/context/SignOutContext";
import { seedSyncState, useDbMigrations } from "@/db/client";
import { SyncRoot } from "@/sync/SyncRoot";
import { fontAssets } from "@/theme/type";

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts(fontAssets);
  const migrations = useDbMigrations();
  const session = useSession();

  useEffect(() => {
    if (migrations.success) seedSyncState();
  }, [migrations.success]);

  // On launch, a revoked or expired session key sends the user back to sign-in.
  useEffect(() => {
    if (session.status !== "signedIn") return;
    apiFetch("/me", { sessionKey: session.sessionKey }).catch((error) => {
      if (error instanceof UnauthorizedError) void clearSession();
    });
  }, [session.status, session.sessionKey]);

  if (migrations.error) return <NativeText>Migration error: {migrations.error.message}</NativeText>;
  if (fontError) return <NativeText>Font error: {fontError.message}</NativeText>;
  // Render nothing until the local database is ready and the fonts are loaded.
  if (!migrations.success || !fontsLoaded || session.status === "loading") return null;

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <StatusBar style="auto" />
      {session.status === "signedIn" && (
        <SyncRoot sessionKey={session.sessionKey} onUnauthorized={() => void clearSession()} />
      )}
      <SignOutContext.Provider value={() => void clearSession()}>
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Protected guard={session.status === "signedOut"}>
            <Stack.Screen name="sign-in" />
          </Stack.Protected>
          {/* The guard covers only the screens listed here: a new top-level route must be added to this block or it is reachable signed out. */}
          <Stack.Protected guard={session.status === "signedIn"}>
            <Stack.Screen name="index" />
            <Stack.Screen name="(tabs)" />
            <Stack.Screen name="source/[id]" />
            <Stack.Screen name="topic/[id]" />
            <Stack.Screen name="settings/removed-topics" />
            <Stack.Screen name="share" />
          </Stack.Protected>
        </Stack>
      </SignOutContext.Provider>
    </GestureHandlerRootView>
  );
}
