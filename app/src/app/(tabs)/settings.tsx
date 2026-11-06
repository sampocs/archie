import * as Clipboard from "expo-clipboard";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";

import { newsletterAddressFrom } from "@/account/newsletterAddress";
import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { useSignOut } from "@/context/SignOutContext";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";

/** The Settings tab: the newsletter address, the review reminder, removed topics and sign-out. */
export default function SettingsScreen() {
  const router = useRouter();
  const signOut = useSignOut();
  const newsletterAddress = useNewsletterAddress();

  return (
    <Screen title="Settings">
      {newsletterAddress ? (
        <GroupedList title="NEWSLETTERS">
          <SettingsRow
            testID="newsletter-address-copy"
            label={newsletterAddress}
            labelTestID="newsletter-address"
            trailing="Copy"
            onPress={() => {
              haptic("selection");
              void Clipboard.setStringAsync(newsletterAddress);
            }}
          />
        </GroupedList>
      ) : null}
      <GroupedList title="REVIEW">
        <SettingsRow
          testID="review-settings-link"
          label="Review reminder"
          trailing="›"
          onPress={() => router.push("/settings/review")}
        />
      </GroupedList>
      <GroupedList title="TOPICS">
        <SettingsRow
          testID="removed-topics-link"
          label="Removed topics"
          trailing="›"
          onPress={() => router.push("/settings/removed-topics")}
        />
      </GroupedList>
      <GroupedList title="ACCOUNT">
        <SettingsRow testID="sign-out" label="Sign out" onPress={signOut} />
      </GroupedList>
    </Screen>
  );
}

type SettingsRowProps = {
  testID: string;
  label: string;
  labelTestID?: string;
  trailing?: string;
  onPress: () => void;
};

function SettingsRow({ testID, label, labelTestID, trailing, onPress }: SettingsRowProps) {
  const theme = useTheme();

  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        gap: theme.spacing.md,
        paddingVertical: theme.spacing.md,
        opacity: pressed ? 0.6 : 1,
      })}
    >
      <View style={{ flexShrink: 1 }}>
        <Text testID={labelTestID} numberOfLines={1} selectable={labelTestID !== undefined}>
          {label}
        </Text>
      </View>
      {trailing ? <Text tone="ink3">{trailing}</Text> : null}
    </Pressable>
  );
}

// Fetched each time the tab comes into view; any failure just hides the newsletter row.
function useNewsletterAddress(): string | null {
  const session = useSession();
  const [address, setAddress] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      if (session.status !== "signedIn") return;

      let cancelled = false;
      apiFetch("/me", { sessionKey: session.sessionKey })
        .then((me) => {
          if (!cancelled) setAddress(newsletterAddressFrom(me));
        })
        .catch(() => {
          if (!cancelled) setAddress(null);
        });
      return () => {
        cancelled = true;
      };
    }, [session.status, session.sessionKey]),
  );

  return address;
}
