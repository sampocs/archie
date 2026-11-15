import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, View } from "react-native";

import { ChatRow } from "@/ask/ChatRow";
import { confirmDeleteChat, promptChatName } from "@/ask/chatPrompts";
import { historyGroups, matchesChatQuery } from "@/ask/sections";
import { useChats, type ChatListItem } from "@/ask/useChats";
import { deleteConversation, renameConversation } from "@/db/actions";
import { db } from "@/db/client";
import { SwipeRow } from "@/library/SwipeRow";
import { requestSync } from "@/sync/useSync";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { LongPressMenu, type MenuItem } from "@/ui/NativeMenu";
import { useNow } from "@/ui/useNow";

/** Past chats, searchable, grouped Today / This week / Earlier. */
export default function HistoryScreen() {
  const theme = useTheme();
  const router = useRouter();
  const chats = useChats();
  const now = useNow();
  const [query, setQuery] = useState("");
  const groups = historyGroups(
    chats.filter((chat) => matchesChatQuery(chat, query)),
    now,
  );

  return (
    <Screen title="History" nav={{ title: "History", backLabel: "Ask" }} onBack={router.back}>
      <TextField
        testID="history-search"
        placeholder="Search chats"
        value={query}
        onChangeText={setQuery}
        autoCorrect={false}
        clearButtonMode="while-editing"
      />
      {chats.length === 0 ? (
        <Text testID="history-empty" tone="ink2">
          No chats yet.
        </Text>
      ) : groups.length === 0 ? (
        <Text testID="history-no-match" tone="ink2">
          No chats match.
        </Text>
      ) : (
        groups.map((group) => (
          <View key={group.key} testID={`history-group-${group.key}`}>
            <Text variant="kicker" tone="ink3" style={{ paddingBottom: theme.spacing.xs }}>
              {group.label}
            </Text>
            {group.items.map((chat, index) => (
              <View key={chat.conversation.id}>
                {index > 0 ? (
                  <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: theme.colors.line }} />
                ) : null}
                <HistoryRow chat={chat} now={now} />
              </View>
            ))}
          </View>
        ))
      )}
    </Screen>
  );
}

function HistoryRow({ chat: { conversation, lastAnswer }, now }: { chat: ChatListItem; now: Date }) {
  return (
    <SwipeRow
      actions={[
        {
          key: "delete",
          label: "Delete",
          tone: "missed",
          testID: `swipe-delete-chat-${conversation.id}`,
          onPress: () => {
            deleteConversation(db, conversation.id);
            haptic("success");
            requestSync();
          },
        },
      ]}
    >
      <LongPressMenu items={chatMenuItems(conversation)}>
        <ChatRow conversation={conversation} lastAnswer={lastAnswer} now={now} />
      </LongPressMenu>
    </SwipeRow>
  );
}

/** A History row's long-press menu: Rename, then Delete (after its confirmation) in red. */
function chatMenuItems(conversation: { id: string; title: string }): MenuItem[] {
  return [
    {
      label: "Rename",
      testID: "ask-menu-rename",
      icon: "pencil",
      onPress: () =>
        promptChatName({
          currentTitle: conversation.title,
          onSubmit: (title) => {
            renameConversation(db, conversation.id, title);
            requestSync();
          },
        }),
    },
    {
      label: "Delete",
      testID: "ask-menu-delete",
      icon: "trash",
      destructive: true,
      onPress: () =>
        confirmDeleteChat(() => {
          deleteConversation(db, conversation.id);
          haptic("success");
          requestSync();
        }),
    },
  ];
}
