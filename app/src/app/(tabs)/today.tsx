import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useEffect, useState } from "react";
import { Pressable } from "react-native";

import { newsletterAddressFrom } from "@/account/newsletterAddress";
import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { useSignOut } from "@/context/SignOutContext";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

export default function TodayScreen() {
  const theme = useTheme();
  const signOut = useSignOut();
  const session = useSession();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [newsletterAddress, setNewsletterAddress] = useState<string | null>(null);

  // Fetched each time the sheet opens; any failure just hides the row.
  useEffect(() => {
    if (!sheetOpen || session.status !== "signedIn") return;

    let cancelled = false;
    apiFetch("/me", { sessionKey: session.sessionKey })
      .then((me) => {
        if (!cancelled) setNewsletterAddress(newsletterAddressFrom(me));
      })
      .catch(() => {
        if (!cancelled) setNewsletterAddress(null);
      });
    return () => {
      cancelled = true;
    };
  }, [sheetOpen, session.status, session.sessionKey]);

  const accountButton = (
    <Pressable testID="account-button" accessibilityLabel="Account" hitSlop={12} onPress={() => setSheetOpen((open) => !open)}>
      <Ionicons name="person-circle-outline" size={28} color={theme.colors.ink2} />
    </Pressable>
  );

  return (
    <Screen title="Today" headerRight={accountButton}>
      {/* Inline sheet rather than Alert, which Maestro can't drive reliably. */}
      {sheetOpen ? (
        <Card style={{ gap: theme.spacing.sm }}>
          {newsletterAddress ? (
            <>
              <Text variant="kicker" tone="ink2">
                Newsletter address
              </Text>
              <Text testID="newsletter-address" selectable>
                {newsletterAddress}
              </Text>
              <Button
                testID="newsletter-address-copy"
                label="Copy"
                variant="secondary"
                onPress={() => void Clipboard.setStringAsync(newsletterAddress)}
              />
            </>
          ) : null}
          <Button testID="sign-out" label="Sign out" variant="secondary" onPress={signOut} />
        </Card>
      ) : null}
    </Screen>
  );
}
