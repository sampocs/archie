import { Ionicons } from "@expo/vector-icons";
import { eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import * as Network from "expo-network";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pressable, View } from "react-native";

import { ChatThread, useChatThread } from "@/ask/ChatThread";
import { Composer } from "@/ask/Composer";
import { useAskAvailable } from "@/ask/useAskAvailable";
import { useCardChat } from "@/ask/useCardChat";
import { useChat } from "@/ask/useChats";
import { dropCard } from "@/db/actions";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { VersionsSheet } from "@/edits/VersionsSheet";
import { type CardPill, cardPills, cardSourceLink } from "@/review/cardPage";
import { detailLines } from "@/review/detail";
import { isReviewable, type ReviewData } from "@/review/eligibility";
import { cardKicker } from "@/review/kicker";
import { KIND_LABELS } from "@/review/labels";
import { cardDueLabel } from "@/review/summary";
import type { CardRow } from "@/review/types";
import { DetailBullets } from "@/review/ui/DetailBullets";
import { GRADE_SIGNALS } from "@/review/ui/VerdictPill";
import { useReviewData } from "@/review/useReviewData";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { Kicker } from "@/ui/Kicker";
import { MenuSheet } from "@/ui/MenuSheet";
import { Toast } from "@/ui/Toast";
import { useNow } from "@/ui/useNow";

// A card shows at most this many detail lines, as the review session does.
const MAX_DETAIL_LINES = 5;

/**
 * A card's own page: the card as a record (question, answer, detail), its pills, where it came from, Practice and
 * Remove, and a chat about the card under it for changing it. The chat waits for the phone's chats to be read, so
 * reopening the card continues its latest chat instead of starting a new one.
 */
export default function CardScreen() {
  const theme = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const chat = useCardChat(id);
  if (!chat.loaded) return <View style={{ flex: 1, backgroundColor: theme.colors.bg }} />;
  // A new chat id (the chat was deleted elsewhere) starts the page's chat state over.
  return <CardPage key={chat.conversationId} cardId={id} conversationId={chat.conversationId} />;
}

function CardPage({ cardId, conversationId }: { cardId: string; conversationId: string }) {
  const theme = useTheme();
  const router = useRouter();
  const now = useNow();
  const data = useReviewData();
  const { data: cards, updatedAt: cardsRead } = useLiveQuery(
    db.select().from(schema.cards).where(eq(schema.cards.id, cardId)),
    [cardId],
  );
  const card = cards[0]?.deletedAt === null ? cards[0] : null;

  // The chat about this card: the first question creates it, about the card.
  const { messages } = useChat(conversationId);
  const about = useMemo(() => ({ kind: "card" as const, id: cardId }), [cardId]);
  const thread = useChatThread({ conversationId, messages, about });
  const available = useAskAvailable();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;

  const [expanded, setExpanded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  // Stable, so a re-render (a pull landing) doesn't restart the toast's timer.
  const hideToast = useCallback(() => setToast(null), []);

  // An edit applied in the chat (a new version landing) opens the card back up to show its new wording.
  const hasChat = thread.messages.length > 0 || thread.pending !== null;
  const shownVersion = useRef<number | null>(null);
  useEffect(() => {
    if (!card) return;
    if (hasChat && shownVersion.current !== null && card.version > shownVersion.current) {
      setExpanded(true);
      setToast("Card updated");
    }
    shownVersion.current = card.version;
  }, [card, hasChat]);

  // Sending folds the card back to its question, so the exchange has the room.
  const threadSend = thread.send;
  const send = useCallback(
    (text: string, web: boolean) => {
      setExpanded(false);
      threadSend(text, web);
    },
    [threadSend],
  );

  function remove(): void {
    dropCard(db, cardId);
    requestSync();
    haptic("success");
    router.back();
  }

  if (cardsRead !== undefined && !card) {
    return (
      <Screen title="Card" nav={{ title: "Card", backLabel: "Back" }} onBack={router.back}>
        <Text testID="card-page-gone" tone="ink2">
          This card was removed.
        </Text>
      </Screen>
    );
  }
  if (!card) return <View style={{ flex: 1, backgroundColor: theme.colors.bg }} />;

  const collapsed = hasChat && !expanded;
  const edited = card.version > 1;

  return (
    <View style={{ flex: 1 }}>
      <Screen
        title="Card"
        nav={{ title: "Card", backLabel: "Back" }}
        onBack={router.back}
        headerRight={
          <Pressable testID="card-more" accessibilityLabel="More" hitSlop={12} onPress={() => setMenuOpen(true)}>
            <Ionicons name="ellipsis-horizontal" size={24} color={theme.colors.ink} />
          </Pressable>
        }
        footer={
          available === false ? (
            <Text testID="ask-unavailable" tone="ink2">
              Ask isn't available on this account
            </Text>
          ) : (
            <Composer
              placeholder="Ask to change this card…"
              disabled={!online}
              disabledLabel="Ask needs a connection"
              sendDisabled={(thread.pending !== null && !thread.pending.live.failed) || thread.unanswered === "waiting"}
              onSend={send}
            />
          )
        }
      >
        <View testID="card-page" style={{ gap: theme.spacing.lg }}>
          <Pressable
            testID="card-page-card"
            accessibilityRole={hasChat ? "button" : undefined}
            disabled={!hasChat}
            onPress={() => setExpanded((current) => !current)}
          >
            <CardRecord card={card} data={data} now={now} collapsed={collapsed} />
          </Pressable>
          {collapsed ? null : (
            <CardFacts
              card={card}
              data={data}
              now={now}
              onPractice={() => router.push(`/review/session?mode=card&id=${card.id}`)}
              onRemove={remove}
            />
          )}
          <ChatThread thread={{ ...thread, send }} online={online} onToast={setToast} />
        </View>
      </Screen>
      <MenuSheet
        visible={menuOpen}
        onClose={() => setMenuOpen(false)}
        items={[
          ...(edited ? [{ testID: "card-menu-versions", label: "Versions", onPress: () => setVersionsOpen(true) }] : []),
          { testID: "card-menu-remove", startsGroup: edited, label: "Remove", destructive: true, onPress: remove },
        ]}
      />
      <VersionsSheet
        target={edited ? { kind: "card", id: card.id } : null}
        visible={versionsOpen}
        onClose={() => setVersionsOpen(false)}
        onRestored={(version) => setToast(`Restored version ${version}`)}
      />
      {/* Outside the scroll view, so it pins to the screen's bottom rather than the end of the chat. */}
      {toast ? <Toast message={toast} onHide={hideToast} /> : null}
    </View>
  );
}

type CardRecordProps = { card: CardRow; data: ReviewData; now: Date; collapsed: boolean };

/** The card: kicker (kind · due) and question, then (unless collapsed) a dashed rule, the answer and its detail. */
function CardRecord({ card, data, now, collapsed }: CardRecordProps) {
  const theme = useTheme();
  const lines = detailLines(card.detail).slice(0, MAX_DETAIL_LINES);

  return (
    <Card style={{ gap: collapsed ? theme.spacing.xs : theme.spacing.md }}>
      <Kicker
        testID="card-page-kicker"
        domain={cardKicker(card, data).domain}
        label={KIND_LABELS[card.kind] ?? card.kind}
        suffix={cardDueLabel(card, data, now)}
      />
      <Text
        testID="card-page-question"
        variant={collapsed ? "headline" : "reviewQuestion"}
        style={collapsed ? undefined : { fontSize: 22 }}
      >
        {card.question}
      </Text>
      {collapsed ? null : (
        <>
          <View style={{ borderTopWidth: 1, borderStyle: "dashed", borderColor: theme.colors.line }} />
          <Text testID="card-page-answer" variant="readingBody">
            {card.answer}
          </Text>
          <DetailBullets testID="card-page-detail" lines={lines} tone="ink2" />
        </>
      )}
    </Card>
  );
}

type CardFactsProps = { card: CardRow; data: ReviewData; now: Date; onPractice: () => void; onRemove: () => void };

/** The pills, the "From <title> ›" row, and Practice / Remove. */
function CardFacts({ card, data, now, onPractice, onRemove }: CardFactsProps) {
  const theme = useTheme();
  const router = useRouter();
  const source = cardSourceLink(card, data);

  return (
    <View style={{ gap: theme.spacing.md }}>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
        {cardPills(card, data, now).map((pill) => (
          <PillView key={pill.kind} pill={pill} />
        ))}
      </View>
      {source ? (
        <Pressable
          testID="card-page-source"
          accessibilityRole="button"
          onPress={() => router.push({ pathname: source.pathname, params: { id: source.id } })}
          style={{ flexDirection: "row", justifyContent: "space-between", gap: theme.spacing.md }}
        >
          <Text tone="ink2" numberOfLines={1} style={{ flex: 1 }}>
            From {source.title}
          </Text>
          <Text tone="ink3">›</Text>
        </Pressable>
      ) : null}
      <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
        <View style={{ flex: 1 }}>
          <Button
            testID="card-page-practice"
            variant="secondary"
            label="Practice"
            disabled={!isReviewable(card, data, now)}
            onPress={onPractice}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Button testID="card-page-remove" variant="secondary" label="Remove" onPress={onRemove} />
        </View>
      </View>
    </View>
  );
}

/** One meta pill; the "Last:" pill takes its grade's colour. */
function PillView({ pill }: { pill: CardPill }) {
  const theme = useTheme();
  const color = pill.grade ? theme.signals[GRADE_SIGNALS[pill.grade]] : undefined;

  return (
    <View
      testID={`card-page-pill-${pill.kind}`}
      style={{
        backgroundColor: theme.colors.surface,
        borderWidth: 1,
        borderColor: theme.colors.cardEdge,
        borderRadius: theme.radii.chipSmall,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.xs,
      }}
    >
      <Text variant="secondary" tone="ink2" style={color ? { color } : undefined}>
        {pill.label}
      </Text>
    </View>
  );
}
