import { useLocalSearchParams, useRouter } from "expo-router";
import * as Network from "expo-network";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ionicons } from "@expo/vector-icons";
import { eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { Alert, Pressable, View } from "react-native";

import { aboutTitleOf } from "@/ask/aboutTitle";
import { AnswerView } from "@/ask/AnswerView";
import { CardSetProposal } from "@/ask/CardSetProposal";
import {
  cardSetChoice,
  choiceLine,
  MAKE_CARDS_MESSAGE,
  seededTicks,
  shownCardSetStatus,
  storedChoice,
  ticksOf,
  viewOfCardSetWire,
  type CardSetChoice,
  type CardSetView,
} from "@/ask/cardSets";
import { backLabelOf } from "@/ask/chatChrome";
import { Composer } from "@/ask/Composer";
import { ItemSheet } from "@/ask/ItemSheet";
import { groupSections, liveView } from "@/ask/sections";
import { parseSegments, type AboutKind } from "@/ask/types";
import { useAskAvailable } from "@/ask/useAskAvailable";
import { useCardSetTicks, useChatItemId, useConversationCardSets } from "@/ask/useCardSets";
import { useChat } from "@/ask/useChats";
import { useChatSession } from "@/ask/useChatSession";
import { deleteConversation } from "@/db/actions";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { EditProposalCard } from "@/edits/EditProposalCard";
import { viewOfWire } from "@/edits/types";
import { useConversationProposals } from "@/edits/useProposals";
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
  const cardSets = useConversationCardSets(params.id);
  const { ticks, toggle } = useCardSetTicks();
  // Ticks an earlier question stored back a set up after a remount; toggled ticks win over them.
  const ticksFor = useCallback(
    (view: Pick<CardSetView, "id" | "cards">) => ticksOf(ticks, view, seededTicks(messages, view)),
    [ticks, messages],
  );
  // The next question carries the open set's ticks when some card is unticked. Only a stored set can be open then: a
  // live answer blocks sending until its rows land. The latest proposed one is the open one.
  const openStoredSet = useMemo(
    () => [...cardSets.values()].flat().findLast((cardSet) => cardSet.status === "proposed") ?? null,
    [cardSets],
  );
  const choice = useMemo(
    () => cardSetChoice(openStoredSet, openStoredSet ? ticksFor(openStoredSet) : []),
    [openStoredSet, ticksFor],
  );
  const { pending, send } = useChatSession({ conversationId: params.id, messages, about, cardSetChoice: choice });
  const proposals = useConversationProposals(params.id);
  // Targets with a proposal in the live answer: older still-proposed ones for them are superseded.
  const liveTargets = new Set((pending?.live.proposals ?? []).map((wire) => `${wire.target_kind}:${wire.target_id}`));
  // A set in the live answer replaces every still-proposed stored one, as the server does when it saves it.
  const cardSetLive = (pending?.live.cardSets.length ?? 0) > 0;
  // Once the chat has saved its Library item, a later Save updates that item.
  const updating = useChatItemId(params.id) !== null;
  // While a set waits on a decision, the composer invites changes to it.
  const openCardSet =
    (pending?.live.cardSets ?? []).some((wire) => wire.status === "proposed") ||
    [...cardSets.values()].flat().some((cardSet) => shownCardSetStatus(cardSet, cardSetLive) === "proposed");
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
  const turns = useMemo(() => messages.filter((message) => message.id !== pending?.userMessageId), [messages, pending]);

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
                  borderColor: theme.colors.line,
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
                sendDisabled={pending !== null && !pending.live.failed}
                onSend={send}
              />
            )}
          </View>
        }
      >
        <View testID="chat-screen" style={{ gap: theme.spacing.lg }}>
          {turns.map((message, index) =>
            message.role === "user" ? (
              <UserBubble key={message.id} text={message.text} index={index} choice={storedChoice(message.segments)} />
            ) : (
              <AnswerView
                key={message.id}
                index={index}
                sections={groupSections(parseSegments(message.segments))}
                quietLabels={(proposals.get(message.id) ?? []).length > 0 || cardSets.has(message.id)}
                failed={message.status === "failed"}
                onRetry={() => retry(turns, index, send)}
                onMakeCards={
                  // An answer that already proposed cards has its own Save; offering Make cards there too is noise.
                  message.status === "complete" && !cardSets.has(message.id)
                    ? () => send(MAKE_CARDS_MESSAGE, false)
                    : undefined
                }
              >
                {(proposals.get(message.id) ?? []).map((proposal) => (
                  <EditProposalCard
                    key={proposal.id}
                    proposal={proposal}
                    ready
                    online={online}
                    supersededLive={liveTargets.has(`${proposal.targetKind}:${proposal.targetId}`)}
                    onToast={setToast}
                  />
                ))}
                {(cardSets.get(message.id) ?? []).map((cardSet) => (
                  <CardSetProposal
                    key={cardSet.id}
                    cardSet={cardSet}
                    ready
                    online={online}
                    replacedLive={cardSetLive}
                    updating={updating}
                    kept={ticksFor(cardSet)}
                    onToggle={(index) => toggle(cardSet, index, seededTicks(messages, cardSet))}
                    onToast={setToast}
                  />
                ))}
              </AnswerView>
            ),
          )}
          {pending ? (
            <>
              <UserBubble text={pending.text} index={turns.length} choice={pending.cardSetChoice} />
              <AnswerView
                index={turns.length + 1}
                {...liveView(pending.live)}
                sentAt={pending.sentAt}
                quietLabels={pending.live.proposals.length > 0 || pending.live.cardSets.length > 0}
                failed={pending.live.failed}
                onRetry={() => send(pending.text, pending.webSearch)}
              >
                {pending.live.proposals.map((wire) => (
                  <EditProposalCard
                    key={wire.id}
                    proposal={viewOfWire(wire)}
                    ready={pending.live.messageId !== null}
                    online={online}
                    onToast={setToast}
                  />
                ))}
                {pending.live.cardSets.map((wire) => {
                  const view = viewOfCardSetWire(wire);
                  return (
                    <CardSetProposal
                      key={wire.id}
                      cardSet={view}
                      ready={pending.live.messageId !== null}
                      online={online}
                      updating={updating}
                      kept={ticksFor(view)}
                      onToggle={(index) => toggle(view, index, seededTicks(messages, view))}
                      onToast={setToast}
                    />
                  );
                })}
              </AnswerView>
            </>
          ) : null}
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
            testID: "chat-menu-delete",
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

/** Asks before deleting, saying that what was saved from the chat outlives it. */
function confirmDeleteChat(onConfirm: () => void): void {
  Alert.alert("Delete this chat?", "Cards and Library items you saved from it stay.", [
    { text: "Cancel", style: "cancel" },
    { text: "Delete", style: "destructive", onPress: onConfirm },
  ]);
}

/** Try again on a stored failed answer: send its question again, with the globe as it was. */
function retry(
  turns: { role: string; text: string; webSearch: number }[],
  answerIndex: number,
  send: (text: string, web: boolean) => void,
): void {
  const question = turns.slice(0, answerIndex).findLast((turn) => turn.role === "user");
  if (question) send(question.text, question.webSearch === 1);
}

/** A question, with a muted "Kept 3 of 5 cards" under it when it carried the open card set's Keep ticks. */
function UserBubble({ text, index, choice }: { text: string; index: number; choice: CardSetChoice | null }) {
  const theme = useTheme();
  return (
    <View style={{ alignSelf: "flex-end", alignItems: "flex-end", maxWidth: "85%", gap: theme.spacing.xs }}>
      <View
        testID={`chat-user-${index}`}
        style={{
          backgroundColor: theme.colors.bubble,
          borderRadius: theme.radii.card,
          paddingHorizontal: theme.spacing.md,
          paddingVertical: theme.spacing.sm,
        }}
      >
        <Text>{text}</Text>
      </View>
      {choice ? (
        <Text testID={`chat-user-${index}-kept`} variant="secondary" tone="ink3">
          {choiceLine(choice)}
        </Text>
      ) : null}
    </View>
  );
}
