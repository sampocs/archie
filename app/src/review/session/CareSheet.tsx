import { useState } from "react";

import { apiFetch } from "@/api/client";
import { setCardAnswer } from "@/db/actions";
import { db } from "@/db/client";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { BottomSheet } from "@/ui/BottomSheet";
import { haptic } from "@/ui/haptics";

// The care endpoint takes a note of up to 500 characters.
const MAX_NOTE_LENGTH = 500;

type CareSheetProps = { cardId: string; sessionKey: string | null; visible: boolean; onClose: () => void };

/** "What I care about…": the server rewrites the card's answer around the note; the phone keeps the new answer. */
export function CareSheet({ cardId, sessionKey, visible, onClose }: CareSheetProps) {
  const theme = useTheme();
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);

  async function save(): Promise<void> {
    setSaving(true);
    setFailed(false);
    const body = await apiFetch(`/review/cards/${cardId}/care`, {
      method: "POST",
      body: { note: note.trim() },
      sessionKey,
    }).catch(() => null);
    setSaving(false);

    // Any failure (offline, the model, a card deleted meanwhile) gets the same retry line.
    const answer = (body as { answer?: unknown } | null)?.answer;
    if (typeof answer !== "string") {
      setFailed(true);
      return;
    }
    setCardAnswer(db, cardId, answer);
    haptic("success");
    setNote("");
    onClose();
  }

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="care-sheet">
      <Text variant="headline">What do you want to remember about this?</Text>
      <TextField
        testID="care-input"
        value={note}
        onChangeText={setNote}
        maxLength={MAX_NOTE_LENGTH}
        multiline
        autoFocus
      />
      {failed ? (
        <Text testID="care-error" variant="secondary" style={{ color: theme.signals.missed }}>
          Couldn't save. Try again.
        </Text>
      ) : null}
      <Button testID="care-save" label="Save" onPress={save} disabled={note.trim() === "" || saving} />
    </BottomSheet>
  );
}
