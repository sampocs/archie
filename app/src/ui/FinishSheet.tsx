import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";

import type { Reaction } from "@/capture/types";
import { finishSource, setCardsOff } from "@/db/actions";
import { db } from "@/db/client";
import { readingMinutes } from "@/library/primer";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import type { Signal } from "@/theme/tokens";
import { useTheme } from "@/theme/useTheme";

import { BottomSheet } from "./BottomSheet";
import { haptic } from "./haptics";

// `primerWords` gives the queued primer's reading time; null while the primer is still being written. `cardsOff` is the
// source's "No cards for this", which the cards row starts from. `book` turns the sheet into a book's "Finished it":
// thoughts only.
type FinishSheetProps = {
  sourceId: string;
  primerWords: number | null;
  cardsOff: boolean;
  book?: { title: string };
  visible: boolean;
  onClose: () => void;
};

const VERDICTS: { reaction: Reaction; label: string; signal: Signal }[] = [
  { reaction: "easy", label: "Easy", signal: "gotIt" },
  { reaction: "mostly", label: "Mostly followed", signal: "partly" },
  { reaction: "lost", label: "Parts lost me", signal: "missed" },
];

/**
 * "How'd it go?": both the verdict and the note are optional, so Save alone marks the source done. "Parts lost me"
 * adds a "Queue the primer" row, ticked by default, so Save also queues the primer unless it's unticked. "Make review
 * cards" starts ticked unless the source's cards are off; Save applies a change to it like "No cards for this". A book's
 * variant ("Finished <title>") asks only what stuck, which steers its refresher and cards; Done finishes it.
 */
export function FinishSheet({ sourceId, primerWords, cardsOff, book, visible, onClose }: FinishSheetProps) {
  const theme = useTheme();
  const [reaction, setReaction] = useState<Reaction | null>(null);
  const [note, setNote] = useState("");
  const [queuePrimer, setQueuePrimer] = useState(true);
  const [makeCards, setMakeCards] = useState(!cardsOff);

  // Start the cards row from the source's current setting each time the sheet opens, since the menu or a pull can
  // change it while the sheet is closed.
  useEffect(() => {
    if (visible) setMakeCards(!cardsOff);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  function save(): void {
    const withPrimer = reaction === "lost" && queuePrimer;
    // Cards go off before the finish, so a finished newsletter isn't analyzed into cards that are then retired.
    if (!book && makeCards === cardsOff) setCardsOff(db, sourceId, !makeCards);
    finishSource(db, { sourceId, reaction, note: note.trim() || null, queuePrimer: withPrimer });
    haptic("success");
    requestSync();
    onClose();
  }

  if (book) {
    return (
      <BottomSheet visible={visible} onClose={onClose} testID="finish-sheet">
        <Text variant="headline">{`Finished ${book.title}`}</Text>
        <TextField
          testID="finish-note"
          placeholder="What stuck with you?"
          value={note}
          onChangeText={setNote}
          maxLength={2000}
          multiline
        />
        <Text variant="secondary" tone="ink3">
          Archie researches the book and writes a refresher and cards, focused on what you mention.
        </Text>
        <Button testID="finish-save" label="Done" onPress={save} />
      </BottomSheet>
    );
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
      {reaction === "lost" ? (
        <CheckRow
          testID="finish-queue-primer"
          title="Queue the primer"
          detail={`${primerLength(primerWords)} so you can come back to it`}
          checked={queuePrimer}
          onToggle={() => setQueuePrimer((current) => !current)}
        />
      ) : null}
      <CheckRow
        testID="finish-make-cards"
        title="Make review cards"
        detail="Untick for things you don't need to remember"
        checked={makeCards}
        onToggle={() => setMakeCards((current) => !current)}
      />
      {/* The mic waits for voice input (a follow-up); typing works now. */}
      <TextField
        testID="finish-note"
        placeholder="Anything confusing? (optional)"
        value={note}
        onChangeText={setNote}
        multiline
      />
      <Button testID="finish-save" label="Save" onPress={save} />
    </BottomSheet>
  );
}

function primerLength(primerWords: number | null): string {
  return primerWords === null ? "◆" : `◆ ${readingMinutes(primerWords)} min ·`;
}

function CheckRow(props: { testID: string; title: string; detail: string; checked: boolean; onToggle: () => void }) {
  const theme = useTheme();
  const box = 22;

  return (
    <Pressable
      testID={props.testID}
      accessibilityRole="checkbox"
      accessibilityState={{ checked: props.checked }}
      onPress={() => {
        haptic("selection");
        props.onToggle();
      }}
      style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md }}
    >
      <View
        style={{
          width: box,
          height: box,
          borderRadius: 6,
          alignItems: "center",
          justifyContent: "center",
          borderWidth: 1.5,
          borderColor: props.checked ? theme.colors.chrome : theme.colors.line,
          backgroundColor: props.checked ? theme.colors.chrome : "transparent",
        }}
      >
        {props.checked ? <Text tone="onChrome">✓</Text> : null}
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="headline">{props.title}</Text>
        <Text variant="secondary" tone="ink3">
          {props.detail}
        </Text>
      </View>
    </Pressable>
  );
}
