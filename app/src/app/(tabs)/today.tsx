import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useEffect, useState } from "react";
import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { newsletterAddressFrom } from "@/account/newsletterAddress";
import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { useSignOut } from "@/context/SignOutContext";
import { upNext, waitingNewsletters } from "@/library/visibility";
import { useLibraryData } from "@/library/useLibraryData";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { sinceLabel, newslettersLine, todayDate } from "@/today/todayLabels";
import { GroupedList } from "@/ui/GroupedList";
import { ItemRow } from "@/ui/ItemRow";
import { QueuedPrimerRow } from "@/ui/QueuedPrimerRow";
import { SourceRow } from "@/ui/SourceRow";
import { useNow } from "@/ui/useNow";

const UP_NEXT_COUNT = 3;

export default function TodayScreen() {
  const theme = useTheme();
  const router = useRouter();
  const now = useNow();
  const data = useLibraryData();
  const signOut = useSignOut();
  const session = useSession();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [newsletterAddress, setNewsletterAddress] = useState<string | null>(
    null,
  );

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

  // Up next is the combined queue: queued sources and queued primers.
  const queued = upNext(data.sources, now);
  const upNextItems = queued.slice(0, UP_NEXT_COUNT);
  const newsletters = waitingNewsletters(data.sources, now);
  const isEmpty = upNextItems.length === 0 && newsletters.count === 0;

  const accountButton = (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: theme.spacing.sm,
      }}
    >
      <Text testID="today-date" variant="monoLabel" tone="ink3">
        {todayDate(now)}
      </Text>
      <Pressable
        testID="account-button"
        accessibilityLabel="Account"
        hitSlop={12}
        onPress={() => setSheetOpen((open) => !open)}
      >
        <Ionicons
          name="person-circle-outline"
          size={28}
          color={theme.colors.ink2}
        />
      </Pressable>
    </View>
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
          <Button
            testID="removed-topics-link"
            label="Removed topics"
            variant="secondary"
            onPress={() => router.push("/settings/removed-topics")}
          />
          <Button
            testID="sign-out"
            label="Sign out"
            variant="secondary"
            onPress={signOut}
          />
        </Card>
      ) : null}

      {upNextItems.length > 0 ? (
        <GroupedList
          title="Up next"
          right={
            <Pressable
              testID="today-see-all"
              onPress={() => router.push({
                  pathname: "/(tabs)/library",
                  params: { filter: "queued", at: String(Date.now()) },
                })}
              hitSlop={8}
            >
              <Text variant="secondary" tone="ink2">
                {`See all ${queued.length} ›`}
              </Text>
            </Pressable>
          }
        >
          {upNextItems.map((entry, index) =>
            entry.kind === "source" ? (
              <SourceRow key={entry.key} source={entry.source} testID={`up-next-${index}`} />
            ) : (
              <QueuedPrimerRow key={entry.key} source={entry.source} testID={`up-next-${index}`} />
            ),
          )}
        </GroupedList>
      ) : null}

      {newsletters.count > 0 && newsletters.since ? (
        <GroupedList title="Newsletters">
          <ItemRow
            testID="today-newsletters"
            artwork={{ imageUrl: null, domain: "Finance", monogram: "✉" }}
            kicker={{ domain: "Finance", label: "Inbox" }}
            title={newslettersLine(newsletters.count)}
            meta={`${newsletters.senders.join(", ")} · ${sinceLabel(newsletters.since, now)}`}
            end={<Text tone="ink3">›</Text>}
            onPress={() => router.push({
                pathname: "/(tabs)/library",
                params: { filter: "inbox", at: String(Date.now()) },
              })}
          />
        </GroupedList>
      ) : null}

      {isEmpty ? (
        <Text testID="today-empty" tone="ink2">
          Nothing waiting. Tap ＋ to add a link, or share one to Archie.
        </Text>
      ) : null}
    </Screen>
  );
}
