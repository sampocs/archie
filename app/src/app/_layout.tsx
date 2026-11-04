import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useEffect, useState } from "react";
import { LogBox, Text as NativeText } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";

import { apiFetch, UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { SignOutContext } from "@/context/SignOutContext";
import { db, seedSyncState, useDbMigrations } from "@/db/client";
import * as schema from "@/db/schema";
import { SyncRoot } from "@/sync/SyncRoot";
import { fontAssets } from "@/theme/type";

// React Native warns this when a native-driven animation (navigation, sheets) updates with no JS listener; it is
// harmless, and its dev toast sits over the tab bar and swallows taps.
LogBox.ignoreLogs(["Sending `onAnimatedValueUpdate` with no listeners registered."]);

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts(fontAssets);
  const migrations = useDbMigrations();
  const session = useSession();

  useEffect(() => {
    if (migrations.success) seedSyncState();
  }, [migrations.success]);

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
      <AppStack />
    </GestureHandlerRootView>
  );
}

// Split from RootLayout because the topic gate reads the local `topics` table, which exists only after the migrations.
function AppStack() {
  const session = useSession();
  const [topicsChosen, setTopicsChosen] = useState<boolean | null>(null);
  const { data: localTopics } = useLiveQuery(db.select({ id: schema.topics.id }).from(schema.topics).limit(1));

  // On launch (and after any sign-in), learn whether the picker is still owed; offline it simply isn't shown.
  // A revoked or expired session key also sends the user back to sign-in.
  useEffect(() => {
    if (session.status !== "signedIn") {
      setTopicsChosen(null);
      return;
    }
    apiFetch("/me", { sessionKey: session.sessionKey })
      .then((me) => setTopicsChosen((me as { topics_chosen?: boolean }).topics_chosen !== false))
      .catch((error) => {
        if (error instanceof UnauthorizedError) void clearSession();
      });
  }, [session.status, session.sessionKey]);

  const needsPicker = session.status === "signedIn" && topicsChosen === false && localTopics.length === 0;

  return (
    <SignOutContext.Provider value={() => void clearSession()}>
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Protected guard={session.status === "signedOut"}>
          <Stack.Screen name="sign-in" />
        </Stack.Protected>
        {/* The guard covers only the screens listed here: a new top-level route must be added to this block or it is reachable signed out. */}
        <Stack.Protected guard={session.status === "signedIn" && !needsPicker}>
          <Stack.Screen name="index" />
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="source/[id]" />
          <Stack.Screen name="topic/[id]" />
          <Stack.Screen name="settings/removed-topics" />
          <Stack.Screen name="share" />
        </Stack.Protected>
        <Stack.Protected guard={needsPicker}>
          <Stack.Screen name="topic-picker" />
        </Stack.Protected>
      </Stack>
    </SignOutContext.Provider>
  );
}
