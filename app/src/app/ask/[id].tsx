import { useLocalSearchParams, useRouter } from "expo-router";
import * as Network from "expo-network";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { View } from "react-native";

import { aboutTitleOf } from "@/ask/aboutTitle";
import { AnswerView } from "@/ask/AnswerView";
import { CardSetProposal } from "@/ask/CardSetProposal";
import { MAKE_CARDS_MESSAGE, shownCardSetStatus, viewOfCardSetWire } from "@/ask/cardSets";
import { Composer } from "@/ask/Composer";
import { groupSections, liveView } from "@/ask/sections";
import { parseSegments, type AboutKind } from "@/ask/types";
import { useAskAvailable } from "@/ask/useAskAvailable";
import { useChatItemId, useConversationCardSets } from "@/ask/useCardSets";
import { useChat } from "@/ask/useChats";
import { useChatSession } from "@/ask/useChatSession";
import { EditProposalCard } from "@/edits/EditProposalCard";
import { viewOfWire } from "@/edits/types";
import { useConversationProposals } from "@/edits/useProposals";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { Toast } from "@/ui/Toast";

type Params = { id: string; q?: string; web?: string; aboutKind?: AboutKind; aboutId?: string; aboutTitle?: string };

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
  const { pending, send } = useChatSession({ conversationId: params.id, messages, about });
  const proposals = useConversationProposals(params.id);
  // Targets with a proposal in the live answer: older still-proposed ones for them are superseded.
  const liveTargets = new Set((pending?.live.proposals ?? []).map((wire) => `${wire.target_kind}:${wire.target_id}`));
  const cardSets = useConversationCardSets(params.id);
  // A set in the live answer replaces every still-proposed stored one, as the server does when it saves it.
  const cardSetLive = (pending?.live.cardSets.length ?? 0) > 0;
  // Once the chat has saved its Library item, a later Save updates that item.
  const updating = useChatItemId(params.id) !== null;
  // While a set waits on a decision, the composer invites changes to it.
  const openCardSet =
    (pending?.live.cardSets ?? []).some((wire) => wire.status === "proposed") ||
    [...cardSets.values()].flat().some((cardSet) => shownCardSetStatus(cardSet, cardSetLive) === "proposed");
  const [toast, setToast] = useState<string | null>(null);
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
  const turns = useMemo(() => messages.filter((message) => message.id !== pending?.userMessageId), [messages, pending]);

  return (
    <View style={{ flex: 1 }}>
      <Screen
        title="Ask"
        nav={{ title: conversation?.title ?? "", backLabel: "Ask" }}
        onBack={router.back}
        footer={
          <View style={{ gap: theme.spacing.sm }}>
            {aboutTitle ? (
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
              <UserBubble key={message.id} text={message.text} index={index} />
            ) : (
              <AnswerView
                key={message.id}
                index={index}
                sections={groupSections(parseSegments(message.segments))}
                failed={message.status === "failed"}
                onRetry={() => retry(turns, index, send)}
                onMakeCards={message.status === "complete" ? () => send(MAKE_CARDS_MESSAGE, false) : undefined}
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
                    onToast={setToast}
                  />
                ))}
              </AnswerView>
            ),
          )}
          {pending ? (
            <>
              <UserBubble text={pending.text} index={turns.length} />
              <AnswerView
                index={turns.length + 1}
                {...liveView(pending.live)}
                sentAt={pending.sentAt}
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
                {pending.live.cardSets.map((wire) => (
                  <CardSetProposal
                    key={wire.id}
                    cardSet={viewOfCardSetWire(wire)}
                    ready={pending.live.messageId !== null}
                    online={online}
                    updating={updating}
                    onToast={setToast}
                  />
                ))}
              </AnswerView>
            </>
          ) : null}
        </View>
      </Screen>
      {/* Outside the scroll view, so it pins to the screen's bottom rather than the end of the chat. */}
      {toast ? <Toast message={toast} onHide={hideToast} /> : null}
    </View>
  );
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

function UserBubble({ text, index }: { text: string; index: number }) {
  const theme = useTheme();
  return (
    <View
      testID={`chat-user-${index}`}
      style={{
        alignSelf: "flex-end",
        maxWidth: "85%",
        backgroundColor: theme.colors.press,
        borderRadius: theme.radii.card,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
      }}
    >
      <Text>{text}</Text>
    </View>
  );
}
