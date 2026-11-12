import { useCallback, useEffect, useMemo, useState } from "react";
import { View } from "react-native";

import { EditProposalCard } from "@/edits/EditProposalCard";
import { viewOfWire } from "@/edits/types";
import { useConversationProposals } from "@/edits/useProposals";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { AnswerView } from "./AnswerView";
import { CardSetProposal } from "./CardSetProposal";
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
} from "./cardSets";
import { makeCardsAnswerId } from "./makeCards";
import { groupSections, liveView, STILL_ANSWERING, unansweredState } from "./sections";
import { parseSegments, type AboutKind, type MessageRow } from "./types";
import { useCardSetTicks, useChatItemId, useConversationCardSets } from "./useCardSets";
import { useChatSession, type PendingQuestion } from "./useChatSession";

// How often a chat waiting on an answer the server is still finishing asks for a sync.
const ANSWER_POLL_MS = 5_000;

/** Everything a chat's thread reads and does, from `useChatThread`; the screen around it reads the first four. */
export type ChatThreadState = {
  pending: PendingQuestion | null;
  send: (text: string, webSearch: boolean) => void;
  // A question with no answer and no overlay: still being finished ("waiting") or given up on ("failed").
  unanswered: "waiting" | "failed" | null;
  // While a card set waits on a decision, the composer invites changes to it.
  openCardSet: boolean;
  messages: MessageRow[];
  cardSets: Map<string, CardSetView[]>;
  ticksFor: (view: Pick<CardSetView, "id" | "cards">) => boolean[];
  toggle: (view: Pick<CardSetView, "id" | "cards">, index: number, seeded: boolean[] | null) => void;
  proposals: ReturnType<typeof useConversationProposals>;
  updating: boolean;
  aboutKind: string | null;
};

/**
 * A chat's thread state: its stored card sets and proposals, the Keep ticks, the live question (`useChatSession`), and
 * the unanswered-question poll. `about` is sent with the question that creates the chat.
 */
export function useChatThread(input: {
  conversationId: string;
  messages: MessageRow[];
  about: { kind: AboutKind; id: string } | null;
  // What the stored chat is about, for a chat opened after it was created (`about` is only for the first question).
  aboutKind?: string | null;
}): ChatThreadState {
  const { conversationId, messages, about } = input;
  const cardSets = useConversationCardSets(conversationId);
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
  const { pending, send } = useChatSession({ conversationId, messages, about, cardSetChoice: choice });

  // A question with no answer and no overlay (the app was relaunched, or the chat reopened): the server may still be
  // finishing it. Poll for the answer while it is young, and re-read the clock so it turns failed after 3 minutes.
  const [, setTick] = useState(0);
  const unanswered = pending ? null : unansweredState(messages, Date.now());
  useEffect(() => {
    if (unanswered !== "waiting") return;
    const poll = setInterval(() => {
      requestSync();
      setTick((tick) => tick + 1);
    }, ANSWER_POLL_MS);
    return () => clearInterval(poll);
  }, [unanswered]);

  const proposals = useConversationProposals(conversationId);
  // Once the chat has saved its Library item, a later Save updates that item.
  const updating = useChatItemId(conversationId) !== null;
  const cardSetLive = (pending?.live.cardSets.length ?? 0) > 0;
  const openCardSet =
    (pending?.live.cardSets ?? []).some((wire) => wire.status === "proposed") ||
    [...cardSets.values()].flat().some((cardSet) => shownCardSetStatus(cardSet, cardSetLive) === "proposed");

  const aboutKind = input.aboutKind ?? about?.kind ?? null;
  return { pending, send, unanswered, openCardSet, messages, cardSets, ticksFor, toggle, proposals, updating, aboutKind };
}

type ChatThreadProps = { thread: ChatThreadState; online: boolean; onToast: (message: string) => void };

/**
 * A chat's turns: stored questions and answers (with their edit proposals and card sets), an unanswered question's
 * waiting or failed answer, and the live question's overlay.
 */
export function ChatThread({ thread, online, onToast }: ChatThreadProps) {
  const { pending, send, unanswered, messages, cardSets, ticksFor, toggle, proposals, updating, aboutKind } = thread;
  const turns = useMemo(() => messages.filter((message) => message.id !== pending?.userMessageId), [messages, pending]);
  const makeCardsOn = makeCardsAnswerId({
    turns,
    hasCardSet: (id) => cardSets.has(id),
    aboutKind,
    questionInFlight: pending !== null || unanswered !== null,
  });
  const unansweredQuestion = unanswered ? messages.at(-1) : undefined;
  // Targets with a proposal in the live answer: older still-proposed ones for them are superseded.
  const liveTargets = new Set((pending?.live.proposals ?? []).map((wire) => `${wire.target_kind}:${wire.target_id}`));
  // A set in the live answer replaces every still-proposed stored one, as the server does when it saves it.
  const cardSetLive = (pending?.live.cardSets.length ?? 0) > 0;

  return (
    <>
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
            onMakeCards={message.id === makeCardsOn ? () => send(MAKE_CARDS_MESSAGE, false) : undefined}
          >
            {(proposals.get(message.id) ?? []).map((proposal) => (
              <EditProposalCard
                key={proposal.id}
                proposal={proposal}
                ready
                online={online}
                supersededLive={liveTargets.has(`${proposal.targetKind}:${proposal.targetId}`)}
                onToast={onToast}
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
                onToast={onToast}
              />
            ))}
          </AnswerView>
        ),
      )}
      {unansweredQuestion ? (
        <AnswerView
          index={turns.length}
          sections={[]}
          thinking={unanswered === "waiting" ? STILL_ANSWERING : null}
          sentAt={new Date(unansweredQuestion.createdAt).getTime()}
          failed={unanswered === "failed"}
          onRetry={() => send(unansweredQuestion.text, unansweredQuestion.webSearch === 1)}
        />
      ) : null}
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
                onToast={onToast}
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
                  onToast={onToast}
                />
              );
            })}
          </AnswerView>
        </>
      ) : null}
    </>
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
