import DateTimePicker from "@react-native-community/datetimepicker";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Switch, View } from "react-native";

import { db } from "@/db/client";
import { getReviewSettings, setReviewSettings, type ReviewSettings } from "@/db/reviewSettings";
import { scheduleReminders } from "@/review/reminderScheduler";
import { dateToMinutes, formatReminderTime, minutesToDate } from "@/review/reminderTime";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { BottomSheet } from "@/ui/BottomSheet";
import { haptic } from "@/ui/haptics";

export default function ReviewSettingsScreen() {
  const router = useRouter();
  const theme = useTheme();
  const [settings, setSettings] = useState<ReviewSettings>(() => getReviewSettings(db));
  const [picking, setPicking] = useState(false);

  // Saved first, then the plan is rebuilt; turning off cancels everything through the empty plan.
  function change(next: ReviewSettings): void {
    setSettings(next);
    setReviewSettings(db, next);
    haptic("selection");
    void scheduleReminders(db, { askPermission: next.reminderEnabled });
  }

  const rowStyle = { flexDirection: "row", alignItems: "center", justifyContent: "space-between" } as const;

  return (
    <Screen title="Review reminder" onBack={router.back}>
      <Card style={{ gap: theme.spacing.md }}>
        <View style={rowStyle}>
          <Text>Daily reminder</Text>
          <Switch
            testID="reminder-toggle"
            value={settings.reminderEnabled}
            onValueChange={(reminderEnabled) => change({ ...settings, reminderEnabled })}
          />
        </View>
        {settings.reminderEnabled ? (
          <Pressable testID="reminder-time-row" onPress={() => setPicking(true)} style={rowStyle}>
            <Text>Time</Text>
            <Text testID="reminder-time" variant="monoLabel" tone="ink3">
              {formatReminderTime(settings.reminderMinutes)}
            </Text>
          </Pressable>
        ) : null}
      </Card>
      <Text testID="reminder-caption" variant="caption" tone="ink3">
        Only sent when cards are due
      </Text>

      <BottomSheet visible={picking} onClose={() => setPicking(false)} testID="reminder-time-sheet">
        <Text variant="headline">Remind me at</Text>
        <DateTimePicker
          value={minutesToDate(settings.reminderMinutes)}
          mode="time"
          display="spinner"
          onChange={(_, time) => time && change({ ...settings, reminderMinutes: dateToMinutes(time) })}
        />
      </BottomSheet>
    </Screen>
  );
}
