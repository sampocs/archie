import { useFonts } from "expo-font";
import { close, openHostApp, type InitialProps } from "expo-share-extension";
import { useEffect, useState } from "react";
import { ScrollView, View } from "react-native";

import { readSharedSessionKey } from "@/auth/keychain";
import { canSaveToCollection, resolveCollectionPick } from "@/capture/collectionChoice";
import { CaptureOptions } from "@/capture/CaptureOptions";
import { CollectionChips } from "@/capture/CollectionChips";
import { CaptureChoice, CollectionPick, EMPTY_CHOICE } from "@/capture/types";
import { readLastCollectionId, readSharedCollections, writeLastCollectionId } from "@/collections/sharedCollections";
import type { SharedCollection } from "@/collections/sharedCollectionsFormat";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { FontScalingContext } from "@/theme/fontScaling";
import { fontAssets } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

import { resolveShare } from "./resolveShare";
import { buildCollectionShareActions, buildShareAction, shareDeepLink, submitShare } from "./submit";

type Phase =
  | { name: "editing" }
  | { name: "saving" }
  | { name: "saved" }
  | { name: "unreachable" }
  | { name: "rejected"; reason: string };

const CLOSE_AFTER_SAVED_MS = 1000;

export function ShareSheet(props: InitialProps) {
  const theme = useTheme();
  const { url, title, capture } = resolveShare(props);
  const [choice, setChoice] = useState<CaptureChoice>(EMPTY_CHOICE);
  const [collections, setCollections] = useState<SharedCollection[]>([]);
  const [lastUsedId, setLastUsedId] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ name: "editing" });

  // Wait for Geist (or its failure) before drawing, as the root layout does, so the sheet doesn't
  // flash the system font.
  const [fontsLoaded, fontError] = useFonts(fontAssets);

  // The app mirrors its collection list into the shared Keychain; unreadable means no collections yet.
  useEffect(() => {
    readSharedCollections()
      .catch(() => [])
      .then(setCollections);
    readLastCollectionId()
      .catch(() => null)
      .then(setLastUsedId);
  }, []);

  const shownPick = resolveCollectionPick(choice.collection, collections, lastUsedId);
  const canSave = choice.intent === "collection"
    ? canSaveToCollection(shownPick, { asksForName: false })
    : choice.intent !== null;

  useEffect(() => {
    if (phase.name !== "saved") return;
    const timer = setTimeout(close, CLOSE_AFTER_SAVED_MS);
    return () => clearTimeout(timer);
  }, [phase.name]);

  async function save(): Promise<void> {
    if (!url || !choice.intent || !canSave) return;
    setPhase({ name: "saving" });

    try {
      const sessionKey = await readSharedSessionKey();
      if (choice.intent === "collection") {
        const { actions, collectionId } = buildCollectionShareActions({ url, pick: shownPick });
        const collectionOutcome = await submitShare(actions, sessionKey);
        if (collectionOutcome === "saved") void writeLastCollectionId(collectionId).catch(() => undefined);
        setPhase(collectionOutcome === "saved" ? { name: "saved" } : { name: "unreachable" });
        return;
      }

      const outcome = await submitShare([buildShareAction({ url, choice, capture })], sessionKey);
      setPhase(outcome === "saved" ? { name: "saved" } : { name: "unreachable" });
    } catch (error) {
      setPhase({ name: "rejected", reason: error instanceof Error ? error.message : String(error) });
    }
  }

  if (!fontsLoaded && !fontError) return <View style={{ flex: 1, backgroundColor: theme.colors.bg }} />;

  return (
    <FontScalingContext.Provider value={false}>
      <View
        testID="share-sheet"
        style={{ flex: 1, backgroundColor: theme.colors.bg, padding: theme.spacing.gutterCards, gap: theme.spacing.lg }}
      >
        {url ? (
          <ShareBody
            {...{ url, title, choice, phase, collections, shownPick, canSave }}
            onChange={setChoice}
            onSave={save}
            onOpenArchie={() => openHostApp(shareDeepLink({ url, choice: { ...choice, collection: shownPick } }))}
          />
        ) : (
          <View style={{ gap: theme.spacing.lg }}>
            <Text variant="headline">Nothing to save here</Text>
            <Button label="Close" onPress={close} />
          </View>
        )}
      </View>
    </FontScalingContext.Provider>
  );
}

type ShareBodyProps = {
  url: string;
  title: string | null;
  choice: CaptureChoice;
  phase: Phase;
  collections: SharedCollection[];
  shownPick: CollectionPick;
  canSave: boolean;
  onChange: (choice: CaptureChoice) => void;
  onSave: () => void;
  onOpenArchie: () => void;
};

function ShareBody({
  url,
  title,
  choice,
  phase,
  collections,
  shownPick,
  canSave,
  onChange,
  onSave,
  onOpenArchie,
}: ShareBodyProps) {
  const theme = useTheme();

  if (phase.name === "saved") {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: theme.spacing.md }}>
        <Text variant="largeTitle">✓</Text>
        <Text variant="headline">Saved to Archie</Text>
      </View>
    );
  }

  if (phase.name === "unreachable") {
    return (
      <View style={{ gap: theme.spacing.lg }}>
        <Text variant="headline">Couldn't reach Archie</Text>
        <Text variant="secondary" tone="ink2">
          Open Archie to save this when you're back online or signed in.
        </Text>
        <Button label="Open Archie" onPress={onOpenArchie} />
        <Button label="Close" variant="secondary" onPress={close} />
      </View>
    );
  }

  const busy = phase.name === "saving";
  return (
    <>
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="headline" numberOfLines={2}>
          {title ?? url}
        </Text>
        <Text variant="secondary" tone="ink3" numberOfLines={1}>
          {url}
        </Text>
      </View>

      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: theme.spacing.lg }}>
        <CaptureOptions
          value={choice}
          onChange={onChange}
          collectionPicker={
            <CollectionChips
              collections={collections}
              pick={shownPick}
              onPick={(collection) => onChange({ ...choice, collection })}
            />
          }
        />
      </ScrollView>

      {phase.name === "rejected" && (
        <Text variant="secondary" tone="ink2">
          {phase.reason}
        </Text>
      )}
      <Button label={busy ? "Saving…" : "Save"} disabled={busy || !canSave} onPress={onSave} />
      <Button label="Cancel" variant="secondary" onPress={close} />
    </>
  );
}
