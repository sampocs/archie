import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { relativeTime, rowPreview } from "./sections";
import { parseSegments, type ConversationRow, type MessageRow } from "./types";

type ChatRowProps = { conversation: ConversationRow; lastAnswer: MessageRow | null; now: Date };

/** A History row: the title and when the chat last moved, with the last answer's opening below it. */
export function ChatRow({ conversation, lastAnswer, now }: ChatRowProps) {
  const theme = useTheme();
  const router = useRouter();
  const preview = rowPreview(parseSegments(lastAnswer?.segments ?? null));

  return (
    <Pressable
      testID={`ask-row-${conversation.id}`}
      onPress={() => router.push({ pathname: "/ask/[id]", params: { id: conversation.id } })}
      // No card around the rows, but the page color stays opaque so a swipe slides the row over its actions.
      style={{ gap: theme.spacing.xs, paddingVertical: theme.spacing.md, backgroundColor: theme.colors.bg }}
    >
      <View style={{ flexDirection: "row", alignItems: "baseline", gap: theme.spacing.md }}>
        <Text variant="headline" numberOfLines={1} style={{ flex: 1 }}>
          {conversation.title}
        </Text>
        <Text variant="secondary" tone="ink3">
          {relativeTime(conversation.updatedAt, now)}
        </Text>
      </View>
      {preview ? (
        <Text variant="secondary" tone="ink2" numberOfLines={2}>
          {preview}
        </Text>
      ) : null}
    </Pressable>
  );
}
