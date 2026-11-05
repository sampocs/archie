import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import { useState } from "react";

import { CaptureOptions } from "@/capture/CaptureOptions";
import { CaptureChoice, EMPTY_CHOICE } from "@/capture/types";
import { addSource } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";

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
  const canSave = isHttpUrl(url) && choice.intent !== null;

  // Clipboard is read only on this tap, never automatically.
  async function paste(): Promise<void> {
    setUrl(await Clipboard.getStringAsync());
  }

  async function save(): Promise<void> {
    if (!choice.intent) return;

    await addSource(db, {
      url: url.trim(),
      intent: choice.intent,
      reaction: choice.reaction,
      note: choice.note.trim(),
      queuePrimer: choice.queuePrimer,
    });
    requestSync();
    setUrl("");
    setChoice(EMPTY_CHOICE);
    router.navigate("/library");
  }

  return (
    <Screen title="Add">
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
      <CaptureOptions value={choice} onChange={setChoice} />
      <Button testID="add-save" label="Save" disabled={!canSave} onPress={save} />
    </Screen>
  );
}
