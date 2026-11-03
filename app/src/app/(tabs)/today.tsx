import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable } from "react-native";

import { useSignOut } from "@/context/SignOutContext";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { useTheme } from "@/theme/useTheme";

export default function TodayScreen() {
  const theme = useTheme();
  const signOut = useSignOut();
  const [sheetOpen, setSheetOpen] = useState(false);

  const accountButton = (
    <Pressable testID="account-button" accessibilityLabel="Account" hitSlop={12} onPress={() => setSheetOpen((open) => !open)}>
      <Ionicons name="person-circle-outline" size={28} color={theme.colors.ink2} />
    </Pressable>
  );

  return (
    <Screen title="Today" headerRight={accountButton}>
      {/* Inline sheet rather than Alert, which Maestro can't drive reliably. */}
      {sheetOpen ? (
        <Card>
          <Button testID="sign-out" label="Sign out" variant="secondary" onPress={signOut} />
        </Card>
      ) : null}
    </Screen>
  );
}
