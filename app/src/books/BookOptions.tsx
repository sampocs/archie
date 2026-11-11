import { useState } from "react";
import { Image, Pressable, StyleSheet, View } from "react-native";

import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";

import { BOOK_STATES, bookMatchLine, type BookChoice, type BookMatch, type BookState } from "./books";

// Shared by the app's + sheet and the share extension, so it only uses theme components and react-native.

const STATE_LABELS: Record<BookState, string> = { reading: "Reading", finished: "Finished" };
const COVER_HEIGHT = 72;

/** The matched book: its cover (when there is one), title and "author · year". */
export function BookMatchCard({ match }: { match: Pick<BookMatch, "title" | "author" | "year" | "coverUrl"> }) {
  const theme = useTheme();
  const [coverFailed, setCoverFailed] = useState(false);
  const line = bookMatchLine(match);

  return (
    <Card testID="book-match" style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md }}>
      {match.coverUrl && !coverFailed ? (
        <Image
          testID="book-match-cover"
          source={{ uri: match.coverUrl }}
          onError={() => setCoverFailed(true)}
          style={{
            width: (COVER_HEIGHT * 2) / 3,
            height: COVER_HEIGHT,
            borderRadius: 4,
            backgroundColor: theme.colors.press,
          }}
        />
      ) : null}
      <View style={{ flex: 1, gap: theme.spacing.xs }}>
        <Text testID="book-match-title" variant="headline" numberOfLines={3}>
          {match.title}
        </Text>
        {line ? (
          <Text testID="book-match-line" variant="secondary" tone="ink2" numberOfLines={2}>
            {line}
          </Text>
        ) : null}
      </View>
    </Card>
  );
}

/** Reading | Finished, and under Finished the optional "What stuck with you?" box. */
export function BookOptions({ value, onChange }: { value: BookChoice; onChange: (choice: BookChoice) => void }) {
  const theme = useTheme();

  return (
    <View style={{ gap: theme.spacing.md }}>
      <View style={{ flexDirection: "row", backgroundColor: theme.colors.press, borderRadius: 10, padding: 2 }}>
        {BOOK_STATES.map((state) => (
          <Pressable
            key={state}
            testID={`book-state-${state}`}
            accessibilityRole="tab"
            accessibilityState={{ selected: state === value.state }}
            onPress={() => onChange({ ...value, state })}
            style={[
              { flex: 1, alignItems: "center", paddingVertical: theme.spacing.sm, borderRadius: 8 },
              state === value.state ? { backgroundColor: theme.colors.surface } : null,
              state === value.state && theme.scheme === "light" ? styles.shadow : null,
            ]}
          >
            <Text variant="secondary" tone={state === value.state ? "ink" : "ink3"}>
              {STATE_LABELS[state]}
            </Text>
          </Pressable>
        ))}
      </View>
      {value.state === "finished" ? (
        <TextField
          testID="book-note"
          value={value.note}
          onChangeText={(note) => onChange({ ...value, note })}
          placeholder="What stuck with you? (optional)"
          maxLength={2000}
          multiline
        />
      ) : (
        <Text variant="secondary" tone="ink3">
          You'll get a spoiler-free primer now. Tap Finished it on the book when you're done.
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  shadow: { shadowColor: "#0E0E0C", shadowOpacity: 0.1, shadowRadius: 2, shadowOffset: { width: 0, height: 1 } },
});
