import DateTimePicker from "@react-native-community/datetimepicker";
import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, Switch, View } from "react-native";

import { db } from "@/db/client";
import { getReviewSettings, setReviewSettings, type ReviewSettings } from "@/db/reviewSettings";
import { stepDailyLimit } from "@/review/dailyCap";
import { scheduleReminders } from "@/review/reminderScheduler";
import { dateToMinutes, formatReminderTime, minutesToDate } from "@/review/reminderTime";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
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
  const down = stepDailyLimit(settings.dailyLimit, -1);
  const up = stepDailyLimit(settings.dailyLimit, 1);

  return (
    <Screen title="Review" onBack={router.back}>
      <Card style={rowStyle}>
        <View style={{ gap: 2, flex: 1 }}>
          <Text>Cards per day</Text>
          <Text variant="secondary" tone="ink3">
            Extra cards wait for the next day
          </Text>
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}>
          <StepButton
            testID="daily-limit-down"
            label="−"
            onPress={down ? () => change({ ...settings, dailyLimit: down.value }) : undefined}
          />
          <Text testID="daily-limit" style={{ minWidth: 28, textAlign: "center" }}>
            {settings.dailyLimit === null ? "Off" : String(settings.dailyLimit)}
          </Text>
          <StepButton
            testID="daily-limit-up"
            label="+"
            onPress={up ? () => change({ ...settings, dailyLimit: up.value }) : undefined}
          />
        </View>
      </Card>

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
            <Text testID="reminder-time" tone="ink2">
              {formatReminderTime(settings.reminderMinutes)}
            </Text>
          </Pressable>
        ) : null}
      </Card>
      <Text testID="reminder-caption" variant="secondary" tone="ink3">
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

// One side of the cards-per-day stepper; without `onPress` it is disabled and dimmed.
function StepButton({ label, onPress, testID }: { label: string; onPress?: () => void; testID: string }) {
  const theme = useTheme();
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ disabled: !onPress }}
      disabled={!onPress}
      onPress={onPress}
      hitSlop={6}
      style={{
        width: 32,
        height: 32,
        borderRadius: 8,
        backgroundColor: theme.colors.press,
        alignItems: "center",
        justifyContent: "center",
        opacity: onPress ? 1 : 0.4,
      }}
    >
      <Text style={{ fontFamily: fontFamily.semibold }}>{label}</Text>
    </Pressable>
  );
}
