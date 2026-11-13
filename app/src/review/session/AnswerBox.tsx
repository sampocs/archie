import { Pressable, StyleSheet, TextInput, View } from "react-native";

import type { RecorderStatus } from "@/review/useRecorder";
import { Card } from "@/theme/components/Card";
import { useAllowFontScaling } from "@/theme/fontScaling";
import { Text } from "@/theme/components/Text";
import { textStyles } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

// The grade endpoint takes up to 4000 characters.
const MAX_ANSWER_LENGTH = 4000;
const ROUND_BUTTON = 36;
const MIN_BOX_HEIGHT = 210;
// About six lines: past this the answer scrolls inside the box, so a long transcript can't push the box and its
// ↑ under the keyboard, where neither can be reached.
const MAX_INPUT_HEIGHT = 160;

type AnswerBoxProps = {
  value: string;
  onChangeText: (text: string) => void;
  onSubmit: () => void;
  onDrop: () => void;
  // Hidden offline: transcription needs the server.
  showMic: boolean;
  micStatus: RecorderStatus;
  onMic: () => void;
};

/** The white answer card: type or dictate, then ↑ (or "Show answer" with an empty box); Drop sits bottom-left. */
export function AnswerBox({ value, onChangeText, onSubmit, onDrop, showMic, micStatus, onMic }: AnswerBoxProps) {
  const theme = useTheme();
  const allowFontScaling = useAllowFontScaling();
  const empty = value.trim() === "";

  return (
    <Card style={[styles.box, { borderRadius: theme.radii.textBox, gap: theme.spacing.md }]}>
      <TextInput
        testID="review-answer-input"
        multiline
        allowFontScaling={allowFontScaling}
        value={value}
        onChangeText={onChangeText}
        maxLength={MAX_ANSWER_LENGTH}
        placeholder="Type or say your answer"
        placeholderTextColor={theme.colors.ink3}
        style={[textStyles.readingBody, styles.input, { color: theme.colors.ink }]}
      />
      <View style={styles.toolbar}>
        <Pressable
          testID="review-drop"
          accessibilityRole="button"
          onPress={onDrop}
          hitSlop={8}
          style={{
            backgroundColor: theme.colors.press,
            borderRadius: theme.radii.chipSmall,
            paddingHorizontal: theme.spacing.md,
            paddingVertical: 7,
          }}
        >
          <Text variant="secondary" tone="ink2" style={{ fontFamily: textStyles.headline.fontFamily }}>
            Drop
          </Text>
        </Pressable>
        <View style={[styles.tools, { gap: theme.spacing.sm }]}>
          {showMic ? (
            <Pressable
              testID="review-mic"
              accessibilityRole="button"
              accessibilityLabel={micStatus === "recording" ? "Stop recording" : "Record your answer"}
              onPress={onMic}
              disabled={micStatus === "transcribing"}
              style={[
                styles.round,
                {
                  backgroundColor: micStatus === "recording" ? theme.signals.missed : theme.colors.press,
                  opacity: micStatus === "transcribing" ? 0.4 : 1,
                },
              ]}
            >
              <Text style={micStatus === "recording" ? { color: "#FFFFFF" } : undefined}>
                {micStatus === "recording" ? "■" : micStatus === "transcribing" ? "…" : "🎙"}
              </Text>
            </Pressable>
          ) : null}
          <Pressable
            testID="review-submit"
            accessibilityRole="button"
            accessibilityLabel={empty ? "Show answer" : "Submit answer"}
            onPress={onSubmit}
            style={[
              empty ? styles.pill : styles.round,
              { backgroundColor: theme.colors.chrome, paddingHorizontal: empty ? theme.spacing.md : 0 },
            ]}
          >
            <Text variant="headline" tone="onChrome" style={empty ? { fontSize: 13.5 } : undefined}>
              {empty ? "Show answer" : "↑"}
            </Text>
          </Pressable>
        </View>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  box: { minHeight: MIN_BOX_HEIGHT, justifyContent: "space-between" },
  input: { flexGrow: 1, minHeight: 120, maxHeight: MAX_INPUT_HEIGHT, textAlignVertical: "top", padding: 0 },
  toolbar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  tools: { flexDirection: "row", alignItems: "center" },
  round: {
    width: ROUND_BUTTON,
    height: ROUND_BUTTON,
    borderRadius: ROUND_BUTTON / 2,
    alignItems: "center",
    justifyContent: "center",
  },
  pill: { height: ROUND_BUTTON, borderRadius: ROUND_BUTTON / 2, alignItems: "center", justifyContent: "center" },
});
