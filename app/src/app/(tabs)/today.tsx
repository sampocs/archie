import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useEffect, useState } from "react";
import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { newsletterAddressFrom } from "@/account/newsletterAddress";
import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { useSignOut } from "@/context/SignOutContext";
import { setPrepMe } from "@/db/actions";
import { db } from "@/db/client";
import { primersReady, upNext, waitingNewsletters } from "@/library/visibility";
import { useLibraryData } from "@/library/useLibraryData";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { sinceLabel, newslettersLine, todayDate } from "@/today/todayLabels";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { ItemRow } from "@/ui/ItemRow";
import { PRIMER_MONOGRAM } from "@/ui/monogram";
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

  const primers = primersReady(data, now);
  const queued = upNext(data.sources, now);
  const upNextItems = queued.slice(0, UP_NEXT_COUNT);
  const newsletters = waitingNewsletters(data.sources, now);
  const isEmpty =
    primers.length === 0 && upNextItems.length === 0 && newsletters.count === 0;

  function togglePrepMe(sourceId: string, on: boolean): void {
    haptic("selection");
    setPrepMe(db, sourceId, !on);
    requestSync();
  }

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

      {primers.length > 0 ? (
        <GroupedList title="Primers ready" testID="today-primers">
          {primers.map((item, index) =>
            item.kind === "source" ? (
              <ItemRow
                key={item.key}
                testID={`primer-ready-${index}`}
                artwork={{
                  imageUrl: null,
                  domain: item.source.domain,
                  monogram: PRIMER_MONOGRAM,
                  unread: true,
                }}
                kicker={{ domain: item.source.domain, suffix: "Background" }}
                title={item.source.title ?? item.source.url}
                meta={
                  item.source.reaction === "lost"
                    ? "You said parts lost you"
                    : "You asked to prep this"
                }
                onPress={() =>
                  router.push({
                    pathname: "/source/[id]",
                    params: { id: item.source.id, primer: "1" },
                  })
                }
              />
            ) : (
              <ItemRow
                key={item.key}
                testID={`primer-ready-${index}`}
                artwork={{
                  imageUrl: null,
                  domain: item.topic.domain,
                  monogram: PRIMER_MONOGRAM,
                  unread: true,
                }}
                kicker={{ domain: item.topic.domain, suffix: "Topic primer" }}
                title={item.topic.name}
                meta="You added this topic"
                onPress={() =>
                  router.push({
                    pathname: "/topic/[id]",
                    params: { id: item.topic.id, primer: "1" },
                  })
                }
              />
            ),
          )}
        </GroupedList>
      ) : null}

      {upNextItems.length > 0 ? (
        <GroupedList
          title="Up next"
          right={
            <Pressable
              testID="today-see-all"
              onPress={() => router.push("/(tabs)/library?filter=queued")}
              hitSlop={8}
            >
              <Text variant="secondary" tone="ink2">
                {`See all ${queued.length} ›`}
              </Text>
            </Pressable>
          }
        >
          {upNextItems.map((source, index) => (
            <SourceRow
              key={source.id}
              source={source}
              testID={`up-next-${index}`}
              end={
                <PrepChip
                  testID={`prep-${index}`}
                  on={source.prepMe === 1}
                  onPress={() => togglePrepMe(source.id, source.prepMe === 1)}
                />
              }
            />
          ))}
        </GroupedList>
      ) : null}

      {newsletters.count > 0 && newsletters.since ? (
        <GroupedList>
          <ItemRow
            testID="today-newsletters"
            artwork={{ imageUrl: null, domain: "Finance", monogram: "✉" }}
            kicker={{ domain: "Finance", label: "Inbox" }}
            title={newslettersLine(newsletters.count)}
            meta={`${newsletters.senders.join(", ")} · ${sinceLabel(newsletters.since, now)}`}
            end={<Text tone="ink3">›</Text>}
            onPress={() => router.push("/(tabs)/library?filter=inbox")}
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

/** The "Prep me" toggle on an Up next row: filled when on. */
function PrepChip({
  testID,
  on,
  onPress,
}: {
  testID: string;
  on: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      hitSlop={8}
      style={{
        backgroundColor: on ? theme.colors.chrome : theme.colors.press,
        borderRadius: theme.radii.button,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.xs,
      }}
    >
      <Text variant="secondary" tone={on ? "onChrome" : "ink"}>
        {on ? "Prepping" : "Prep me"}
      </Text>
    </Pressable>
  );
}
