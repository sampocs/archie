import DateTimePicker from "@react-native-community/datetimepicker";
import { useState } from "react";
import { Pressable, View } from "react-native";

import { snooze, type PrimerTarget } from "@/db/actions";
import { db } from "@/db/client";
import { formatReturnTime, pickedDateUntil, snoozeChoices } from "@/library/snooze";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { BottomSheet } from "./BottomSheet";
import { haptic } from "./haptics";
import { useNow } from "./useNow";

type SnoozeSheetProps = { target: PrimerTarget; id: string; visible: boolean; onClose: () => void };

function ChoiceRow({ testID, label, time, onPress }: { testID: string; label: string; time?: string; onPress: () => void }) {
  const theme = useTheme();
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: theme.spacing.md }}
    >
      <Text>{label}</Text>
      {time ? (
        <Text variant="monoLabel" tone="ink3">
          {time}
        </Text>
      ) : null}
    </Pressable>
  );
}

/** Snooze presets (resolved to a clock time on the right) plus a date picker. */
export function SnoozeSheet({ target, id, visible, onClose }: SnoozeSheetProps) {
  const theme = useTheme();
  const now = useNow();
  const [picking, setPicking] = useState(false);
  const [pickedDay, setPickedDay] = useState(() => new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));

  function choose(until: Date): void {
    snooze(db, target, id, until);
    haptic("success");
    requestSync();
    setPicking(false);
    onClose();
  }

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="snooze-sheet">
      <Text variant="headline">Snooze until</Text>
      {snoozeChoices(now).map((choice) => (
        <ChoiceRow
          key={choice.key}
          testID={`snooze-${choice.key}`}
          label={choice.label}
          time={formatReturnTime(choice.until, now)}
          onPress={() => choose(choice.until)}
        />
      ))}
      <ChoiceRow testID="snooze-pick" label="Pick a date…" onPress={() => setPicking(true)} />
      {picking ? (
        <View style={{ gap: theme.spacing.md }}>
          <DateTimePicker
            value={pickedDay}
            mode="date"
            display="inline"
            minimumDate={new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)}
            onChange={(_, day) => day && setPickedDay(day)}
          />
          <Button
            testID="snooze-pick-confirm"
            label={`Snooze until ${formatReturnTime(pickedDateUntil(pickedDay), now)}`}
            onPress={() => choose(pickedDateUntil(pickedDay))}
          />
        </View>
      ) : null}
    </BottomSheet>
  );
}
