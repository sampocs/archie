import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { relativeTime, rowPreview } from "./sections";
import { parseSegments, type ConversationRow, type MessageRow } from "./types";

type ChatRowProps = { conversation: ConversationRow; lastAnswer: MessageRow | null; now: Date };

/** A saved chat: its title, the last answer's first line, and when it last moved. */
export function ChatRow({ conversation, lastAnswer, now }: ChatRowProps) {
  const theme = useTheme();
  const router = useRouter();
  const preview = rowPreview(parseSegments(lastAnswer?.segments ?? null));

  return (
    <Pressable
      testID={`ask-row-${conversation.id}`}
      onPress={() => router.push({ pathname: "/ask/[id]", params: { id: conversation.id } })}
      style={{
        flexDirection: "row",
        gap: theme.spacing.md,
        paddingVertical: theme.spacing.md,
        paddingHorizontal: theme.spacing.lg,
        backgroundColor: theme.colors.surface,
      }}
    >
      <View style={{ flex: 1, gap: theme.spacing.xs }}>
        <Text variant="headline" numberOfLines={1}>
          {conversation.title}
        </Text>
        {preview ? (
          <Text variant="secondary" tone="ink2" numberOfLines={1}>
            {preview}
          </Text>
        ) : null}
      </View>
      <Text variant="secondary" tone="ink3">
        {relativeTime(conversation.updatedAt, now)}
      </Text>
    </Pressable>
  );
}
