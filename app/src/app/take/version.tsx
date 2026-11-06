import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";
import { View } from "react-native";

import { restoreTakeVersion } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { TakeBody } from "@/takes/TakeBody";
import { shownBody } from "@/takes/takes";
import { useTakesState } from "@/takes/useTakesData";
import { versionKicker } from "@/takes/versionView";
import { Button } from "@/theme/components/Button";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { useNow } from "@/ui/useNow";

export default function TakeVersionScreen() {
  const { id, version } = useLocalSearchParams<{ id: string; version: string }>();
  const router = useRouter();
  const theme = useTheme();
  const now = useNow();
  const { takes, loaded } = useTakesState();
  const take = takes.find((candidate) => candidate.id === id);
  const shown = take?.versions.find((candidate) => candidate.version === Number(version));

  // useLiveQuery answers [] first, so a missing take or version only means "gone" once loaded.
  useEffect(() => {
    if (loaded && !shown) router.back();
  }, [loaded, shown, router]);

  if (!loaded || !take || !shown) return null;

  return (
    <Screen title="" onBack={router.back}>
      <View testID="version-page" style={{ gap: theme.spacing.md }}>
        <Text testID="version-kicker" variant="kicker" tone="ink3">
          {versionKicker(shown, now)}
        </Text>
        <Text variant="largeTitle">{take.title}</Text>
        <TakeBody markdown={shownBody(shown)} />
        {shown.id !== take.current?.id ? (
          // Saved as a new version, as it was; the take's cards are rewritten from it.
          <Button
            testID="version-restore"
            label="Restore this version"
            onPress={() => {
              restoreTakeVersion(db, take.id, shown.version);
              haptic("success");
              requestSync();
              router.back();
            }}
          />
        ) : null}
      </View>
    </Screen>
  );
}
