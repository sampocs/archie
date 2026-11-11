import * as Clipboard from "expo-clipboard";
import * as Network from "expo-network";
import { useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Keyboard, Pressable, View } from "react-native";

import { useSession } from "@/auth/session";
import { lookupBook } from "@/books/api";
import {
  DEFAULT_BOOK_CHOICE,
  isBookQuery,
  LOOKUP_OFFLINE_MESSAGE,
  lookupErrorMessage,
  type BookChoice,
  type BookMatch,
} from "@/books/books";
import { BookMatchCard, BookOptions } from "@/books/BookOptions";
import { CaptureOptions } from "@/capture/CaptureOptions";
import { canSaveToCollection, resolveCollectionPick } from "@/capture/collectionChoice";
import { CollectionDropdown } from "@/capture/CollectionDropdown";
import { isHttpUrl } from "@/capture/extractUrl";
import { CaptureChoice, CollectionPick, EMPTY_CHOICE } from "@/capture/types";
import { promptCollectionName } from "@/collections/prompts";
import { readLastCollectionId } from "@/collections/sharedCollections";
import { saveToCollection } from "@/collections/saveToCollection";
import { useCollectionsData } from "@/collections/useCollectionsData";
import { addBook, addSource } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { isOffline } from "@/review/sessionFlow";
import { haptic } from "@/ui/haptics";

// A typed title is looked up before it can be added; the match stays until the text changes.
type BookLookup =
  | { name: "idle" }
  | { name: "looking" }
  | { name: "failed"; message: string }
  | { name: "matched"; match: BookMatch };

export default function AddScreen() {
  const router = useRouter();
  const theme = useTheme();
  const session = useSession();
  const network = Network.useNetworkState();
  const [url, setUrl] = useState("");
  // The text as last typed, so a lookup answering after an edit is dropped instead of showing a stale match.
  const latestText = useRef("");
  const [lookup, setLookup] = useState<BookLookup>({ name: "idle" });
  const [bookChoice, setBookChoice] = useState<BookChoice>(DEFAULT_BOOK_CHOICE);
  // Text that isn't an http(s) link is a book's title: the link options step aside for Find book.
  const bookMode = isBookQuery(url);
  const [choice, setChoice] = useState<CaptureChoice>(EMPTY_CHOICE);
  const collections = useCollectionsData().map(({ id, name }) => ({ id, name }));
  const [lastUsedId, setLastUsedId] = useState<string | null>(null);
  const shownPick = resolveCollectionPick(choice.collection, collections, lastUsedId);
  const canSave =
    isHttpUrl(url) &&
    (choice.intent === "collection"
      ? canSaveToCollection(shownPick, { asksForName: true })
      : choice.intent !== null);

  useEffect(() => {
    readLastCollectionId()
      .then(setLastUsedId)
      .catch(() => undefined);
  }, []);

  // Editing the text drops an earlier match or failure, so the button reads Find book again.
  function changeText(text: string): void {
    latestText.current = text;
    setUrl(text);
    setLookup({ name: "idle" });
  }

  // Clipboard is read only on this tap, never automatically.
  async function paste(): Promise<void> {
    changeText(await Clipboard.getStringAsync());
  }

  // The lookup needs the server; offline it fails at once with the same message as an unreachable lookup.
  async function findBook(): Promise<void> {
    Keyboard.dismiss();
    if (isOffline(network)) {
      setLookup({ name: "failed", message: LOOKUP_OFFLINE_MESSAGE });
      return;
    }

    const query = url;
    setLookup({ name: "looking" });
    try {
      const match = await lookupBook(query, session.sessionKey);
      if (latestText.current === query) setLookup({ name: "matched", match });
    } catch (error) {
      if (latestText.current === query) setLookup({ name: "failed", message: lookupErrorMessage(error) });
    }
  }

  function saveBook(match: BookMatch): void {
    addBook(db, {
      url: match.url,
      title: match.title,
      author: match.author,
      imageUrl: match.coverUrl,
      state: bookChoice.state,
      note: bookChoice.note,
    });
    haptic("success");
    requestSync();
    router.back();
  }

  // Save drops the link into the collection only: no summary, no cards, nothing in the Library.
  function saveIntoCollection(pick: CollectionPick): void {
    saveToCollection({ url: url.trim(), pick });
    haptic("success");
    requestSync();
    router.back();
  }

  async function save(): Promise<void> {
    if (!choice.intent) return;

    if (choice.intent === "collection") {
      if (shownPick.kind === "new" && !shownPick.name.trim()) {
        promptCollectionName({
          title: "New collection",
          submitLabel: "Create",
          onSubmit: (name) => saveIntoCollection({ kind: "new", name }),
        });
        return;
      }
      saveIntoCollection(shownPick);
      return;
    }

    await addSource(db, {
      url: url.trim(),
      intent: choice.intent,
      reaction: choice.reaction,
      note: choice.note.trim(),
      queuePrimer: choice.queuePrimer,
    });
    requestSync();

    // Save closes the sheet and stays on whatever presented it (Library).
    router.back();
  }

  return (
    <Screen
      title="Add"
      sheet
      headerRight={
        <Pressable testID="add-cancel" onPress={() => router.back()} hitSlop={12}>
          <Text tone="ink2">Cancel</Text>
        </Pressable>
      }
    >
      <Text variant="secondary" tone="ink2">
        Paste a link, or type a book's title.
      </Text>
      {/* The default keyboard: the URL one has no space bar for a title. */}
      <TextField
        testID="add-url"
        value={url}
        onChangeText={changeText}
        placeholder="Link or book title"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="default"
      />
      <Button testID="add-paste" label="Paste" variant="secondary" onPress={paste} />
      {bookMode ? (
        <BookSection lookup={lookup} choice={bookChoice} onChoice={setBookChoice} onFind={findBook} onAdd={saveBook} />
      ) : (
        <>
          <CaptureOptions
            value={choice}
            onChange={(next) => {
              // Picking how to save means the link is in: drop the keyboard so Save (below the options) isn't hidden.
              Keyboard.dismiss();
              setChoice(next);
            }}
            collectionPicker={
              <CollectionDropdown
                collections={collections}
                pick={shownPick}
                onPick={(collection) => setChoice({ ...choice, collection })}
              />
            }
          />
          <Button testID="add-save" label="Save" disabled={!canSave} onPress={save} />
        </>
      )}
      <View style={{ flexDirection: "row", alignItems: "center", gap: 12 }}>
        <View style={{ flex: 1, height: 1, backgroundColor: theme.colors.line }} />
        <Text variant="monoLabel" tone="ink3">
          or
        </Text>
        <View style={{ flex: 1, height: 1, backgroundColor: theme.colors.line }} />
      </View>
      <Pressable
        testID="add-write-take"
        onPress={() => {
          haptic("light");
          router.replace("/take/edit");
        }}
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          backgroundColor: theme.colors.surface,
          borderColor: theme.colors.cardEdge,
          borderWidth: 1,
          borderRadius: 14,
          paddingVertical: 13,
          paddingHorizontal: 14,
          ...(theme.scheme === "light"
            ? { shadowColor: "#0E0E0C", shadowOpacity: 0.06, shadowRadius: 2, shadowOffset: { width: 0, height: 1 } }
            : {}),
        }}
      >
        <Text variant="headline">✎ Write a take</Text>
        <Text tone="ink3">›</Text>
      </Pressable>
    </Screen>
  );
}

type BookSectionProps = {
  lookup: BookLookup;
  choice: BookChoice;
  onChoice: (choice: BookChoice) => void;
  onFind: () => void;
  onAdd: (match: BookMatch) => void;
};

/** Find book until the title matches; then the match, Reading | Finished and Add book. */
function BookSection({ lookup, choice, onChoice, onFind, onAdd }: BookSectionProps) {
  if (lookup.name !== "matched") {
    return (
      <>
        {lookup.name === "failed" ? (
          <Text testID="add-book-error" variant="secondary" tone="ink2">
            {lookup.message}
          </Text>
        ) : null}
        <Button testID="add-find-book" label="Find book" disabled={lookup.name === "looking"} onPress={onFind} />
      </>
    );
  }

  return (
    <>
      <BookMatchCard match={lookup.match} />
      <Text variant="secondary" tone="ink3">
        Not it? Edit the title and search again.
      </Text>
      <BookOptions value={choice} onChange={onChoice} />
      <Button testID="add-book" label="Add book" onPress={() => onAdd(lookup.match)} />
    </>
  );
}
