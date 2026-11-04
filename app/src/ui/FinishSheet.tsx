import { useState } from "react";
import { Pressable, View } from "react-native";

import type { Reaction } from "@/capture/types";
import { finishSource } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import type { Signal } from "@/theme/tokens";
import { useTheme } from "@/theme/useTheme";

import { BottomSheet } from "./BottomSheet";
import { haptic } from "./haptics";

type FinishSheetProps = { sourceId: string; visible: boolean; onClose: () => void };

const VERDICTS: { reaction: Reaction; label: string; signal: Signal }[] = [
  { reaction: "easy", label: "Easy", signal: "gotIt" },
  { reaction: "mostly", label: "Mostly followed", signal: "partly" },
  { reaction: "lost", label: "Parts lost me", signal: "missed" },
];

/** "How'd it go?": both the verdict and the note are optional, so Save alone marks the source done. */
export function FinishSheet({ sourceId, visible, onClose }: FinishSheetProps) {
  const theme = useTheme();
  const [reaction, setReaction] = useState<Reaction | null>(null);
  const [note, setNote] = useState("");

  function save(): void {
    finishSource(db, { sourceId, reaction, note: note.trim() || null });
    haptic("success");
    requestSync();
    onClose();
  }

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="finish-sheet">
      <Text variant="headline">How'd it go?</Text>
      <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
        {VERDICTS.map((verdict) => (
          <Pressable
            key={verdict.reaction}
            testID={`finish-${verdict.reaction}`}
            onPress={() => {
              haptic("selection");
              setReaction((current) => (current === verdict.reaction ? null : verdict.reaction));
            }}
            style={{
              flex: 1,
              borderRadius: theme.radii.chip,
              paddingVertical: theme.spacing.md,
              alignItems: "center",
              borderWidth: 1.5,
              borderColor: reaction === verdict.reaction ? theme.signals[verdict.signal] : theme.colors.line,
            }}
          >
            <Text variant="secondary">{verdict.label}</Text>
          </Pressable>
        ))}
      </View>
      {/* The mic waits for voice input (a follow-up); typing works now. */}
      <TextField
        testID="finish-note"
        placeholder="Anything confusing? (optional)"
        value={note}
        onChangeText={setNote}
        multiline
      />
      <Button testID="finish-save" label="Save" onPress={save} />
      <Text variant="secondary" tone="ink3">
        Both are optional: Save alone marks it done.
      </Text>
    </BottomSheet>
  );
}
