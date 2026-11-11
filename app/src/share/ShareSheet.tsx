import { useFonts } from "expo-font";
import { close, openHostApp, type InitialProps } from "expo-share-extension";
import { useEffect, useState } from "react";
import { ScrollView, View } from "react-native";

import { readSharedSessionKey } from "@/auth/keychain";
import { lookupBook } from "@/books/api";
import {
  DEFAULT_BOOK_CHOICE,
  isGoodreadsBookUrl,
  sharedBookFallback,
  type BookChoice,
  type BookMatch,
} from "@/books/books";
import { BookMatchCard, BookOptions } from "@/books/BookOptions";
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

import { isUnpushedCollectionRejection } from "./rejection";
import { resolveShare } from "./resolveShare";
import {
  buildAddBookAction,
  buildCollectionShareActions,
  buildShareAction,
  shareBookDeepLink,
  shareDeepLink,
  submitShare,
} from "./submit";

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
  // A Goodreads book link is a book: looked up for its cover and author, else added under the shared title.
  const isBook = url !== null && isGoodreadsBookUrl(url);
  const [bookMatch, setBookMatch] = useState<BookMatch | null>(null);
  const [bookChoice, setBookChoice] = useState<BookChoice>(DEFAULT_BOOK_CHOICE);

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

  useEffect(() => {
    if (!url || !isBook) return;
    const fallback = sharedBookFallback(url, capture?.title ?? null);
    readSharedSessionKey()
      .then((sessionKey) => lookupBook(url, sessionKey))
      .catch(() => fallback)
      .then(setBookMatch);
    // The shared URL is fixed for the sheet's life.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  async function saveBook(match: BookMatch): Promise<void> {
    setPhase({ name: "saving" });
    try {
      const outcome = await submitShare([buildAddBookAction({ match, choice: bookChoice })], await readSharedSessionKey());
      setPhase(outcome === "saved" ? { name: "saved" } : { name: "unreachable" });
    } catch (error) {
      setPhase({ name: "rejected", reason: error instanceof Error ? error.message : String(error) });
    }
  }

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
      const reason = error instanceof Error ? error.message : String(error);
      setPhase(isUnpushedCollectionRejection(reason) ? { name: "unreachable" } : { name: "rejected", reason });
    }
  }

  if (!fontsLoaded && !fontError) return <View style={{ flex: 1, backgroundColor: theme.colors.bg }} />;

  return (
    <FontScalingContext.Provider value={false}>
      <View
        testID="share-sheet"
        style={{ flex: 1, backgroundColor: theme.colors.bg, padding: theme.spacing.gutterCards, gap: theme.spacing.lg }}
      >
        {url && isBook ? (
          <BookShareBody
            url={url}
            match={bookMatch}
            choice={bookChoice}
            phase={phase}
            onChange={setBookChoice}
            onSave={saveBook}
            onOpenArchie={(match) => openHostApp(shareBookDeepLink({ match, choice: bookChoice }))}
          />
        ) : url ? (
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

  if (phase.name === "saved" || phase.name === "unreachable") {
    return <OutcomeView saved={phase.name === "saved"} onOpenArchie={onOpenArchie} />;
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

/** After a save: the tick, or (unreachable or signed out) the offer to finish the save in the app. */
function OutcomeView({ saved, onOpenArchie }: { saved: boolean; onOpenArchie: () => void }) {
  const theme = useTheme();

  if (saved) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: theme.spacing.md }}>
        <Text variant="largeTitle">✓</Text>
        <Text variant="headline">Saved to Archie</Text>
      </View>
    );
  }

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

type BookShareBodyProps = {
  url: string;
  // Null while the lookup runs.
  match: BookMatch | null;
  choice: BookChoice;
  phase: Phase;
  onChange: (choice: BookChoice) => void;
  onSave: (match: BookMatch) => void;
  onOpenArchie: (match: BookMatch) => void;
};

/** A shared Goodreads book: the match, Reading | Finished and the thoughts box, then Add book. */
function BookShareBody({ url, match, choice, phase, onChange, onSave, onOpenArchie }: BookShareBodyProps) {
  const theme = useTheme();

  if (match && (phase.name === "saved" || phase.name === "unreachable")) {
    return <OutcomeView saved={phase.name === "saved"} onOpenArchie={() => onOpenArchie(match)} />;
  }

  const busy = phase.name === "saving";
  return (
    <>
      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: theme.spacing.lg }}>
        {match ? (
          <>
            <BookMatchCard match={match} />
            <BookOptions value={choice} onChange={onChange} />
          </>
        ) : (
          <Text variant="secondary" tone="ink3" numberOfLines={1}>
            {`Finding the book… ${url}`}
          </Text>
        )}
      </ScrollView>

      {phase.name === "rejected" && (
        <Text variant="secondary" tone="ink2">
          {phase.reason}
        </Text>
      )}
      <Button
        testID="share-add-book"
        label={busy ? "Saving…" : "Add book"}
        disabled={busy || !match}
        onPress={() => match && onSave(match)}
      />
      <Button label="Cancel" variant="secondary" onPress={close} />
    </>
  );
}
