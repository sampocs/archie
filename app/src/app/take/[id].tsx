import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";

import { retryTakeCleanup } from "@/db/actions";
import { db } from "@/db/client";
import { originLabel } from "@/edits/versions";
import { CardsSection } from "@/item/CardsSection";
import { requestSync } from "@/sync/useSync";
import { RawTextSheet } from "@/takes/RawTextSheet";
import { TakeBody } from "@/takes/TakeBody";
import { TakeMenus } from "@/takes/TakeMenus";
import {
  asTakeKind,
  cleanState,
  earlierVersions,
  shownBody,
  takeDate,
  takePageMeta,
  TAKE_KIND_DOMAIN,
  TAKE_KIND_LABELS,
  type TakeWithVersions,
} from "@/takes/takes";
import { useTakesState } from "@/takes/useTakesData";
import { showsOrigin } from "@/takes/versionView";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { Kicker } from "@/ui/Kicker";
import { useNow } from "@/ui/useNow";

export default function TakeScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const theme = useTheme();
  const now = useNow();
  const { takes, loaded } = useTakesState();
  const take = takes.find((candidate) => candidate.id === id);
  const [menuOpen, setMenuOpen] = useState(false);
  const [rawOpen, setRawOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);

  // Deleted here or elsewhere; useLiveQuery answers [] first, so only leave once the queries have loaded.
  useEffect(() => {
    if (loaded && !take) router.back();
  }, [loaded, take, router]);

  if (!loaded || !take || !take.current) return null;

  const current = take.current;
  const kind = asTakeKind(take.kind);
  const state = cleanState(current);

  return (
    <Screen
      title=""
      onBack={router.back}
      headerRight={
        <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.lg }}>
          <Pressable
            testID="take-edit"
            onPress={() => router.push({ pathname: "/take/edit", params: { id: take.id } })}
            hitSlop={8}
            style={{
              backgroundColor: theme.colors.press,
              borderRadius: theme.radii.button,
              paddingHorizontal: theme.spacing.md,
              paddingVertical: theme.spacing.xs,
            }}
          >
            <Text variant="headline">Edit</Text>
          </Pressable>
          <Pressable testID="take-more" onPress={() => setMenuOpen(true)} hitSlop={12}>
            <Text variant="largeTitle">•••</Text>
          </Pressable>
        </View>
      }
    >
      <View testID="take-page" style={{ gap: theme.spacing.md }}>
        <Kicker testID="take-kicker" domain={TAKE_KIND_DOMAIN[kind]} label={TAKE_KIND_LABELS[kind]} />
        <Text testID="take-title" variant="largeTitle">
          {take.title}
        </Text>
        <Text testID="take-meta" variant="monoLabel" tone="ink3">
          {takePageMeta(take, now)}
        </Text>

        {showsOrigin(state, current) ? (
          <Text testID="take-origin" variant="secondary" tone="ink3">
            Cleaned up from your dictation ·{" "}
            <Text
              testID="take-see-raw"
              variant="secondary"
              tone="ink2"
              style={{ fontWeight: "600" }}
              onPress={() => setRawOpen(true)}
            >
              See what you said ›
            </Text>
          </Text>
        ) : null}
        {state === "cleaning" ? (
          <Text testID="take-cleaning" variant="secondary" tone="ink3">
            Cleaning up…
          </Text>
        ) : null}
        {state === "failed" ? (
          <Text testID="take-clean-failed" variant="secondary" tone="ink3">
            Couldn't clean this up ·{" "}
            <Text
              testID="take-clean-retry"
              variant="secondary"
              tone="ink2"
              style={{ fontWeight: "600" }}
              onPress={() => {
                retryTakeCleanup(db, take.id, current.id);
                haptic("light");
                requestSync();
              }}
            >
              Try again ›
            </Text>
          </Text>
        ) : null}

        <TakeBody testID="take-body" markdown={shownBody(current)} />
        <CardsSection of={{ kind: "take", id: take.id }} backLabel={take.title} />

        {take.versions.length > 1 ? (
          <EarlierVersions
            take={take}
            open={versionsOpen}
            now={now}
            onToggle={() => setVersionsOpen((open) => !open)}
            onOpenVersion={(version) =>
              router.push({ pathname: "/take/version", params: { id: take.id, version: String(version) } })
            }
          />
        ) : null}
      </View>
      <RawTextSheet visible={rawOpen} rawBody={current.rawBody} onClose={() => setRawOpen(false)} />
      <TakeMenus take={take} visible={menuOpen} onClose={() => setMenuOpen(false)} />
    </Screen>
  );
}

type EarlierVersionsProps = {
  take: TakeWithVersions;
  open: boolean;
  now: Date;
  onToggle: () => void;
  onOpenVersion: (version: number) => void;
};

function EarlierVersions({ take, open, now, onToggle, onOpenVersion }: EarlierVersionsProps) {
  const theme = useTheme();

  return (
    <View>
      <Pressable
        testID="take-versions"
        onPress={onToggle}
        style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: theme.spacing.md }}
      >
        <Text variant="headline">Earlier versions</Text>
        <Text tone="ink3">{take.versions.length - 1} ›</Text>
      </Pressable>
      {open
        ? earlierVersions(take).map((version) => (
            <Pressable
              key={version.id}
              testID={`take-version-${version.version}`}
              onPress={() => onOpenVersion(version.version)}
              style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: theme.spacing.sm }}
            >
              <View>
                <Text>Version {version.version}</Text>
                {version.origin !== "owner" ? (
                  <Text variant="secondary" tone="ink3">
                    {originLabel(version.origin)}
                  </Text>
                ) : null}
              </View>
              <Text tone="ink3">{takeDate(version.createdAt, now)}</Text>
            </Pressable>
          ))
        : null}
    </View>
  );
}
