import { useEffect, useState } from "react";
import { View } from "react-native";

import { UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { BottomSheet } from "@/ui/BottomSheet";
import { haptic } from "@/ui/haptics";

import { fetchCardDraft, saveCard } from "./api";

type MakeCardSheetProps = { messageId: string | null; visible: boolean; onClose: () => void; onSaved: () => void };

type DraftState = "drafting" | "drafted" | "failed";

/** A card drafted from one answer, edited by the owner and saved to Review. */
export function MakeCardSheet({ messageId, visible, onClose, onSaved }: MakeCardSheetProps) {
  const theme = useTheme();
  const { sessionKey } = useSession();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [draft, setDraft] = useState<DraftState>("drafting");
  const [saving, setSaving] = useState(false);

  // Each opening drafts afresh; a draft that lands after the owner started typing doesn't overwrite them.
  useEffect(() => {
    if (!visible || !messageId || !sessionKey) return;
    let live = true;
    setQuestion("");
    setAnswer("");
    setDraft("drafting");
    fetchCardDraft(messageId, sessionKey)
      .then((card) => {
        if (!live) return;
        setQuestion((typed) => typed || card.question);
        setAnswer((typed) => typed || card.answer);
        setDraft("drafted");
      })
      .catch((error) => {
        if (error instanceof UnauthorizedError) void clearSession();
        if (live) setDraft("failed");
      });
    return () => {
      live = false;
    };
  }, [visible, messageId, sessionKey]);

  async function save(): Promise<void> {
    if (!messageId) return;
    setSaving(true);
    const saved = await saveCard({ messageId, question, answer, sessionKey: sessionKey ?? "" })
      .then(() => true)
      .catch((error) => {
        if (error instanceof UnauthorizedError) void clearSession();
        return false;
      });
    setSaving(false);

    // A failed save keeps the sheet open with the owner's text, so Save can be tapped again.
    if (!saved) return;
    requestSync();
    haptic("success");
    onSaved();
    onClose();
  }

  const placeholder = draft === "drafting" ? "Drafting…" : undefined;
  const blank = question.trim() === "" || answer.trim() === "";

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="make-card-sheet">
      <Text variant="headline">Make a card</Text>
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="secondary" tone="ink2">
          Question
        </Text>
        <TextField
          testID="card-draft-question"
          value={question}
          onChangeText={setQuestion}
          placeholder={placeholder}
          maxLength={500}
          multiline
        />
      </View>
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="secondary" tone="ink2">
          Answer
        </Text>
        <TextField
          testID="card-draft-answer"
          value={answer}
          onChangeText={setAnswer}
          placeholder={placeholder}
          maxLength={2000}
          multiline
        />
      </View>
      {draft === "failed" ? <Text tone="ink3">Couldn't draft one. Write it yourself.</Text> : null}
      <Button testID="card-draft-save" label="Save" onPress={save} disabled={blank || saving} />
    </BottomSheet>
  );
}
