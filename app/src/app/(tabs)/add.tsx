import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import { useState } from "react";
import { View } from "react-native";

import type { Intent } from "@/capture/types";
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
  const canSubmit = isHttpUrl(url);

  // Clipboard is read only on this tap, never automatically.
  async function paste(): Promise<void> {
    setUrl(await Clipboard.getStringAsync());
  }

  async function submit(intent: Intent): Promise<void> {
    await addSource(db, { url: url.trim(), intent });
    requestSync();
    setUrl("");
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
      <View style={{ gap: 12 }}>
        <Button testID="add-paste" label="Paste" variant="secondary" onPress={paste} />
        <Button testID="add-finished" label="Finished" disabled={!canSubmit} onPress={() => submit("finished")} />
        <Button
          testID="add-queue"
          label="Queue it"
          variant="secondary"
          disabled={!canSubmit}
          onPress={() => submit("queue")}
        />
      </View>
    </Screen>
  );
}
