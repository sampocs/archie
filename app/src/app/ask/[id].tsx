import { useLocalSearchParams, useRouter } from "expo-router";
import * as Network from "expo-network";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ionicons } from "@expo/vector-icons";
import { eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { Pressable, View } from "react-native";

import { aboutTitleOf } from "@/ask/aboutTitle";
import { backLabelOf } from "@/ask/chatChrome";
import { ChatThread, useChatThread } from "@/ask/ChatThread";
import { confirmDeleteChat, promptChatName } from "@/ask/chatPrompts";
import { Composer } from "@/ask/Composer";
import { ItemSheet } from "@/ask/ItemSheet";
import type { AboutKind } from "@/ask/types";
import { useAskAvailable } from "@/ask/useAskAvailable";
import { useChat } from "@/ask/useChats";
import { deleteConversation, renameConversation } from "@/db/actions";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { requestSync } from "@/sync/useSync";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { MenuSheet } from "@/ui/MenuSheet";
import { Toast } from "@/ui/Toast";

type Params = { id: string; q?: string; web?: string; aboutKind?: AboutKind; aboutId?: string; aboutTitle?: string; fromNote?: string };

export default function ChatScreen() {
  const theme = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<Params>();
  const { conversation, messages } = useChat(params.id);
  const available = useAskAvailable();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  const about = useMemo(
    () => (params.aboutKind && params.aboutId ? { kind: params.aboutKind, id: params.aboutId } : null),
    [params.aboutKind, params.aboutId],
  );
  const thread = useChatThread({ conversationId: params.id, messages, about });
  const { pending, send, unanswered, openCardSet } = thread;
  const [toast, setToast] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [itemOpen, setItemOpen] = useState(false);
  // Stable, so a re-render (a pull landing) doesn't restart the toast's timer.
  const hideToast = useCallback(() => setToast(null), []);

  // A question typed on the Ask tab is sent once, when the screen opens.
  const sentFirst = useRef(false);
  useEffect(() => {
    if (sentFirst.current || !params.q || messages.length > 0) return;
    sentFirst.current = true;
    send(params.q, params.web === "1");
  }, [params.q, params.web, messages.length, send]);

  // The opening screen passes the title along; reopening a chat later derives it from the item the chat is about.
  const aboutTitle = useMemo(
    () => params.aboutTitle ?? aboutTitleOf(conversation),
    [params.aboutTitle, conversation],
  );
  // The About chip opens the item only while it is still in the Library; a topic, a take or a gone source stays text.
  const { data: aboutSources } = useLiveQuery(
    db.select().from(schema.sources).where(eq(schema.sources.id, conversation?.aboutSourceId ?? "")),
    [conversation?.aboutSourceId],
  );
  const liveAboutSource = aboutSources[0]?.deletedAt === null ? aboutSources[0] : null;

  return (
    <View style={{ flex: 1 }}>
      <Screen
        title="Ask"
        nav={{ title: conversation?.title ?? "", backLabel: backLabelOf(params.fromNote, aboutTitle) }}
        onBack={router.back}
        headerRight={
          conversation && conversation.deletedAt === null ? (
            <Pressable testID="chat-more" accessibilityLabel="More" hitSlop={12} onPress={() => setMenuOpen(true)}>
              <Ionicons name="ellipsis-horizontal" size={24} color={theme.colors.ink} />
            </Pressable>
          ) : null
        }
        footer={
          <View style={{ gap: theme.spacing.sm }}>
            {aboutTitle && liveAboutSource ? (
              <Pressable
                testID="chat-about"
                accessibilityRole="button"
                onPress={() => setItemOpen(true)}
                style={{
                  alignSelf: "flex-start",
                  maxWidth: "100%",
                  backgroundColor: theme.colors.surface,
                  borderWidth: 1,
                  borderColor: theme.colors.cardEdge,
                  borderRadius: theme.radii.chipSmall,
                  paddingHorizontal: theme.spacing.md,
                  paddingVertical: theme.spacing.xs,
                }}
              >
                <Text variant="secondary" tone="ink2" numberOfLines={1}>
                  ▤ About: {aboutTitle} <Text variant="secondary" tone="ink3">›</Text>
                </Text>
              </Pressable>
            ) : aboutTitle ? (
              <Text testID="chat-about" variant="secondary" tone="ink2">
                About: {aboutTitle}
              </Text>
            ) : null}
            {available === false ? (
              <Text testID="ask-unavailable" tone="ink2">
                Ask isn't available on this account
              </Text>
            ) : (
              <Composer
                placeholder={openCardSet ? "Change something…" : "Ask a follow-up"}
                disabled={!online}
                disabledLabel="Ask needs a connection"
                sendDisabled={(pending !== null && !pending.live.failed) || unanswered === "waiting"}
                onSend={send}
              />
            )}
          </View>
        }
      >
        <View testID="chat-screen" style={{ gap: theme.spacing.lg }}>
          <ChatThread thread={thread} online={online} onToast={setToast} />
        </View>
      </Screen>
      {liveAboutSource ? (
        <ItemSheet sourceId={liveAboutSource.id} visible={itemOpen} onClose={() => setItemOpen(false)} />
      ) : null}
      <MenuSheet
        visible={menuOpen}
        onClose={() => setMenuOpen(false)}
        items={[
          {
            testID: "chat-menu-rename",
            label: "Rename",
            onPress: () =>
              promptChatName({
                currentTitle: conversation?.title ?? "",
                onSubmit: (title) => {
                  renameConversation(db, params.id, title);
                  requestSync();
                },
              }),
          },
          {
            testID: "chat-menu-delete",
            startsGroup: true,
            label: "Delete chat",
            destructive: true,
            onPress: () =>
              confirmDeleteChat(() => {
                deleteConversation(db, params.id);
                haptic("success");
                requestSync();
                router.back();
              }),
          },
        ]}
      />
      {/* Outside the scroll view, so it pins to the screen's bottom rather than the end of the chat. */}
      {toast ? <Toast message={toast} onHide={hideToast} /> : null}
    </View>
  );
}
