import { useState } from "react";
import { randomUUID } from "expo-crypto";
import * as Network from "expo-network";
import { useRouter } from "expo-router";
import { View } from "react-native";

import { ChatRow } from "@/ask/ChatRow";
import { confirmDeleteChat, promptChatName } from "@/ask/chatPrompts";
import { Composer } from "@/ask/Composer";
import { useAskAvailable } from "@/ask/useAskAvailable";
import { useChats } from "@/ask/useChats";
import { deleteConversation, renameConversation } from "@/db/actions";
import { db } from "@/db/client";
import { SwipeRow } from "@/library/SwipeRow";
import { requestSync } from "@/sync/useSync";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";
import { MenuSheet } from "@/ui/MenuSheet";
import { useNow } from "@/ui/useNow";

export default function AskScreen() {
  const router = useRouter();
  const chats = useChats();
  const available = useAskAvailable();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  const now = useNow();
  const [menuFor, setMenuFor] = useState<{ id: string; title: string } | null>(null);

  if (available === false) {
    return (
      <Screen title="Ask">
        <Text testID="ask-unavailable" tone="ink2">
          Ask isn't available on this account
        </Text>
      </Screen>
    );
  }

  return (
    <Screen
      title="Ask"
      footer={
        <Composer
          placeholder="Ask about anything"
          disabled={!online}
          disabledLabel="Ask needs a connection"
          onSend={(text, web) =>
            router.push({ pathname: "/ask/[id]", params: { id: randomUUID(), q: text, web: web ? "1" : "0" } })
          }
        />
      }
    >
      {chats.length === 0 ? (
        <Text testID="ask-empty" tone="ink2">
          Ask a question about anything you've saved.
        </Text>
      ) : (
        <View testID="ask-list">
          <GroupedList>
            {chats.map(({ conversation, lastAnswer }) => (
              <SwipeRow
                key={conversation.id}
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
                <ChatRow
                  conversation={conversation}
                  lastAnswer={lastAnswer}
                  now={now}
                  onLongPress={() => setMenuFor({ id: conversation.id, title: conversation.title })}
                />
              </SwipeRow>
            ))}
          </GroupedList>
        </View>
      )}
      <MenuSheet
        visible={menuFor !== null}
        onClose={() => setMenuFor(null)}
        items={
          menuFor === null
            ? []
            : [
                {
                  label: "Rename",
                  testID: "ask-menu-rename",
                  onPress: () =>
                    promptChatName({
                      currentTitle: menuFor.title,
                      onSubmit: (title) => {
                        renameConversation(db, menuFor.id, title);
                        requestSync();
                      },
                    }),
                },
                {
                  label: "Delete",
                  testID: "ask-menu-delete",
                  destructive: true,
                  startsGroup: true,
                  onPress: () =>
                    confirmDeleteChat(() => {
                      deleteConversation(db, menuFor.id);
                      haptic("success");
                      requestSync();
                    }),
                },
              ]
        }
      />
    </Screen>
  );
}
