import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable } from "react-native";

import { CaptureOptions } from "@/capture/CaptureOptions";
import { canSaveToCollection, resolveCollectionPick } from "@/capture/collectionChoice";
import { CollectionDropdown } from "@/capture/CollectionDropdown";
import { CaptureChoice, CollectionPick, EMPTY_CHOICE } from "@/capture/types";
import { promptCollectionName } from "@/collections/prompts";
import { readLastCollectionId } from "@/collections/sharedCollections";
import { saveToCollection } from "@/collections/saveToCollection";
import { useCollectionsData } from "@/collections/useCollectionsData";
import { addSource } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { haptic } from "@/ui/haptics";

function isHttpUrl(text: string): boolean {
  try {
    const protocol = new URL(text.trim()).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

export default function AddScreen() {
  const router = useRouter();
  const [url, setUrl] = useState("");
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

  // Clipboard is read only on this tap, never automatically.
  async function paste(): Promise<void> {
    setUrl(await Clipboard.getStringAsync());
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
        Paste a link to save it.
      </Text>
      <TextField
        testID="add-url"
        value={url}
        onChangeText={setUrl}
        placeholder="https://"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
      />
      <Button testID="add-paste" label="Paste" variant="secondary" onPress={paste} />
      <CaptureOptions
        value={choice}
        onChange={setChoice}
        collectionPicker={
          <CollectionDropdown
            collections={collections}
            pick={shownPick}
            onPick={(collection) => setChoice({ ...choice, collection })}
          />
        }
      />
      <Button testID="add-save" label="Save" disabled={!canSave} onPress={save} />
    </Screen>
  );
}
