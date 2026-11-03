import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { Text as NativeText } from "react-native";

import { seedSyncState, useDbMigrations } from "@/db/client";
import { SyncRoot } from "@/sync/SyncRoot";
import { fontAssets } from "@/theme/type";

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts(fontAssets);
  const migrations = useDbMigrations();

  useEffect(() => {
    if (migrations.success) seedSyncState();
  }, [migrations.success]);

  if (migrations.error) return <NativeText>Migration error: {migrations.error.message}</NativeText>;
  if (fontError) return <NativeText>Font error: {fontError.message}</NativeText>;
  // Render nothing until the local database is ready and the fonts are loaded.
  if (!migrations.success || !fontsLoaded) return null;

  return (
    <>
      <StatusBar style="auto" />
      {/* Placeholder: Task 9 passes the real session key and clearSession here. */}
      <SyncRoot sessionKey={null} onUnauthorized={() => undefined} />
      <Stack screenOptions={{ headerShown: false }} />
    </>
  );
}
