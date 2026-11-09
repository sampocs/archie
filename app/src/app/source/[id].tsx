import { Ionicons } from "@expo/vector-icons";
import { and, asc, eq, isNull } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useCallback, useEffect, useRef, useState } from "react";
import { Linking, Pressable, StyleSheet, View } from "react-native";

import { db } from "@/db/client";
import { readLater, refreshNote, returnToInbox, setFavorite } from "@/db/actions";
import * as schema from "@/db/schema";
import { useTargetVersions } from "@/edits/useTargetVersions";
import { VersionsSheet } from "@/edits/VersionsSheet";
import { CardsSection } from "@/item/CardsSection";
import { ChatItemBody } from "@/item/ChatItemBody";
import { confirmExplanation, confirmPrompt } from "@/library/confirmations";
import { confirmSignup, dismissSignup } from "@/library/confirmActions";
import { ConfirmPills, SenderPills } from "@/library/ConfirmCard";
import { judgeNewsletterSender } from "@/library/senderActions";
import { SENDER_EXPLANATION, SENDER_KICKER_SUFFIX, senderPrompt } from "@/library/senders";
import { FullEmailSheet } from "@/item/FullEmailSheet";
import { ItemActions } from "@/item/ItemActions";
import { ItemBadgeLine } from "@/item/ItemBadgeLine";
import { ItemHeader, REACTION_LABELS } from "@/item/ItemHeader";
import { ItemMenu } from "@/item/ItemMenu";
import { timestampUrl } from "@/item/timestampLink";
import { useLibraryData } from "@/library/useLibraryData";
import { NoteSources } from "@/notes/NoteSources";
import { OriginalNoteSheet } from "@/notes/OriginalNoteSheet";
import { setPendingRefreshToast } from "@/notes/pendingToast";
import { todayRefresher } from "@/notes/refresher";
import { Markdown } from "@/ui/Markdown";
import { asDomain } from "@/topics/domains";
import { splitFacts } from "@/summary/figures";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import { FinishSheet } from "@/ui/FinishSheet";
import { haptic } from "@/ui/haptics";
import { primerMarkdown, wordCount } from "@/library/primer";
import { CHAT_KIND, kindLabel } from "@/ui/sourceLabels";
import { parseSummary, SummaryContent } from "@/ui/summaryContent";
import { Toast } from "@/ui/Toast";
import { useLocalSearchParams, useRouter } from "expo-router";

type SourceRow = typeof schema.sources.$inferSelect;

export default function SourceScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const theme = useTheme();
  const libraryData = useLibraryData();
  const { data: sources } = useLiveQuery(db.select().from(schema.sources).where(eq(schema.sources.id, id)), [id]);
  const { data: artifacts } = useLiveQuery(
    db
      .select()
      .from(schema.artifacts)
      .where(and(eq(schema.artifacts.sourceId, id), eq(schema.artifacts.isCurrent, 1))),
    [id],
  );
  const { data: cards } = useLiveQuery(
    db
      .select()
      .from(schema.cards)
      .where(and(eq(schema.cards.sourceId, id), isNull(schema.cards.deletedAt)))
      .orderBy(asc(schema.cards.createdAt)),
    [id],
  );

  const { data: topics } = useLiveQuery(
    db.select().from(schema.topics).where(eq(schema.topics.id, sources[0]?.topicId ?? "")),
    [sources[0]?.topicId],
  );
  const [finishOpen, setFinishOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [emailOpen, setEmailOpen] = useState(false);
  const [originalOpen, setOriginalOpen] = useState(false);
  const [queuedToast, setQueuedToast] = useState(false);
  // The ref blocks a second tap within the same render; the state disables the button once it re-renders.
  const refreshStarted = useRef(false);
  const [refreshing, setRefreshing] = useState(false);
  const hideToast = useCallback(() => setQueuedToast(false), []);
  const summaryVersions = useTargetVersions("summary", id).entries.length;
  const primerVersions = useTargetVersions("primer", id).entries.length;
  const [versionsOf, setVersionsOf] = useState<"summary" | "primer" | null>(null);
  const [restoredToast, setRestoredToast] = useState<string | null>(null);
  const hideRestoredToast = useCallback(() => setRestoredToast(null), []);

  const source = sources[0];
  const mergedIntoId = source?.deletedAt ? source.mergedIntoId : null;

  // A duplicate share is tombstoned and points at the source that won; follow it instead of showing the dead row.
  useEffect(() => {
    if (mergedIntoId) router.replace(`/source/${mergedIntoId}`);
  }, [mergedIntoId, router]);

  if (!source || source.deletedAt) return <Screen title="Source" />;

  const starred = source.favoritedAt !== null;
  const isConfirmation = source.confirmUrl !== null;
  const isNote = source.kind === "note";
  const isChat = source.kind === CHAT_KIND;
  const isPendingSender = source.senderPending && !isConfirmation;
  // Both kinds of notice page are bare: no star, menu, badges, actions, summary, note or cards.
  const isNotice = isConfirmation || isPendingSender;
  const summary = artifacts.find((artifact) => artifact.kind === "summary");
  const primer = artifacts.find((artifact) => artifact.kind === "primer");
  const summaryContent = summary ? parseSummary(summary.content) : null;
  const primerWords = primer ? wordCount(primerMarkdown(primer.content)) : null;

  // Done shows while the note waits for its refresh: cards on, not refreshed, write-up written.
  const canRefresh = isNote && source.cardsOff === 0 && source.refreshedAt === null && summaryContent !== null;

  function refresh(): void {
    // Done acts once per visit: a double tap must not refresh twice (the second could reset the queue count).
    if (refreshStarted.current) return;
    refreshStarted.current = true;
    setRefreshing(true);

    const today = todayRefresher(libraryData.sources, new Date());
    const counted = today?.kind === "pick" && today.note.id === source.id;

    refreshNote(db, source.id, counted);
    setPendingRefreshToast({ sourceId: source.id, title: source.title ?? "your note" });
    haptic("success");
    requestSync();
    router.back();
  }

  function addToQueue(): void {
    readLater(db, source.id);
    haptic("success");
    requestSync();
    setQueuedToast(true);
  }

  return (
    <View style={{ flex: 1 }}>
      <Screen
        title=""
        onBack={router.back}
        footer={
          canRefresh ? <Button testID="note-done" label="Done, add review cards" disabled={refreshing} onPress={refresh} /> : undefined
        }
        headerRight={
          isNotice ? undefined : (
            <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.lg }}>
              <Pressable
                testID="item-favorite"
                accessibilityLabel={starred ? "Remove from favorites" : "Add to favorites"}
                onPress={() => {
                  haptic("selection");
                  setFavorite(db, source.id, !starred);
                  requestSync();
                }}
                hitSlop={12}
              >
                <Ionicons
                  name={starred ? "star" : "star-outline"}
                  size={24}
                  color={starred ? theme.signals.favorite : theme.colors.ink}
                />
              </Pressable>
              <Pressable testID="item-more" onPress={() => setMenuOpen(true)} hitSlop={12}>
                <Text variant="largeTitle">•••</Text>
              </Pressable>
            </View>
          )
        }
      >
        <ItemHeader
          source={source}
          topicName={topics[0]?.name ?? null}
          kicker={
            isConfirmation
              ? { label: "Newsletter", suffix: "Signup confirmation" }
              : isPendingSender
                ? { label: "Newsletter", suffix: SENDER_KICKER_SUFFIX }
                : isNote
                  ? { label: "Notes", suffix: source.domain ? asDomain(source.domain) : undefined }
                  : isChat
                    ? { label: kindLabel(CHAT_KIND) }
                    : undefined
          }
        />
        <Text testID="item-title" variant="articleTitle">
          {source.title ?? source.url}
        </Text>
        {isConfirmation ? (
          <ConfirmationPrompt source={source} onDone={router.back} />
        ) : isPendingSender ? (
          <SenderPrompt source={source} onBlocked={router.back} />
        ) : isChat ? (
          <ChatItemBody source={source} primer={primer} />
        ) : isNote ? (
          <>
            {summaryContent ? (
              <>
                <SummarySections summary={summaryContent} source={source} />
                <NoteSources sources={summaryContent.sources ?? []} />
              </>
            ) : (
              <>
                <Text testID="note-write-up-pending" tone="ink2">
                  Archie's write-up is on its way
                </Text>
                <Markdown text={source.noteMarkdown ?? ""} />
              </>
            )}
            {source.noteMarkdown ? (
              <Pressable testID="item-original-note" onPress={() => setOriginalOpen(true)} hitSlop={8}>
                <Text variant="headline">See original note ›</Text>
              </Pressable>
            ) : null}
          </>
        ) : (
          <>
            <ItemBadgeLine source={source} onAddToQueue={addToQueue} />
            <ItemActions source={source} primerWords={primerWords} onFinish={() => setFinishOpen(true)} />
            {summaryContent ? <SummarySections summary={summaryContent} source={source} /> : null}
          </>
        )}
        {source.kind === "newsletter" ? <EmailLinks url={source.url} onOpenEmail={() => setEmailOpen(true)} /> : null}
        {isNotice ? null : (
          <>
            {isNote || isChat ? null : <NoteSection reaction={source.reaction} note={source.note} />}
            <CardsSection of={{ kind: "source", id: source.id }} />
          </>
        )}
        {isNotice ? null : (
          <>
            {isNote ? null : (
              <FinishSheet
                sourceId={source.id}
                primerWords={primerWords}
                visible={finishOpen}
                onClose={() => setFinishOpen(false)}
              />
            )}
            <ItemMenu
              source={source}
              cardCount={cards.length}
              summaryVersions={summaryVersions}
              primerVersions={primerVersions}
              onOpenVersions={setVersionsOf}
              visible={menuOpen}
              onClose={() => setMenuOpen(false)}
            />
            <VersionsSheet
              target={versionsOf ? { kind: versionsOf, id: source.id } : null}
              visible={versionsOf !== null}
              onClose={() => setVersionsOf(null)}
              onRestored={(version) => setRestoredToast(`Restored version ${version}`)}
            />
          </>
        )}
        {isNote && source.noteMarkdown ? (
          <OriginalNoteSheet
            markdown={source.noteMarkdown}
            editedAt={source.noteEditedAt ?? source.createdAt}
            visible={originalOpen}
            onClose={() => setOriginalOpen(false)}
          />
        ) : null}
        <FullEmailSheet sourceId={source.id} visible={emailOpen} onClose={() => setEmailOpen(false)} />
      </Screen>
      {/* Undo sends the reverse action rather than cancelling the first, which may already have synced. */}
      {restoredToast ? <Toast message={restoredToast} onHide={hideRestoredToast} /> : null}
      {queuedToast ? (
        <Toast
          message="Added to your queue"
          actionLabel="Undo"
          onAction={() => {
            returnToInbox(db, source.id);
            haptic("light");
            requestSync();
          }}
          onHide={hideToast}
        />
      ) : null}
    </View>
  );
}

/** A signup confirmation's page: what the email asks, and Confirm / Dismiss; either one deletes it and goes back. */
function ConfirmationPrompt({ source, onDone }: { source: SourceRow; onDone: () => void }) {
  const theme = useTheme();

  async function confirm(): Promise<void> {
    if (await confirmSignup(source)) onDone();
  }

  return (
    <Card style={{ gap: theme.spacing.md }}>
      <Text testID="item-confirm-prompt" variant="headline">
        {confirmPrompt(source)}
      </Text>
      <Text tone="ink2">{confirmExplanation(source)}</Text>
      <ConfirmPills
        confirmTestID="item-confirm"
        dismissTestID="item-dismiss"
        onConfirm={() => void confirm()}
        onDismiss={() => {
          dismissSignup(source.id);
          onDone();
        }}
      />
    </Card>
  );
}

/**
 * A newsletter from a sender nobody has decided on: what the email is, and Allow / Block. Allow leaves the page
 * (it becomes the normal processing page); Block deletes the email and goes back.
 */
function SenderPrompt(props: { source: SourceRow; onBlocked: () => void }) {
  const theme = useTheme();

  return (
    <Card style={{ gap: theme.spacing.md }}>
      <Text testID="item-sender-prompt" variant="headline">
        {senderPrompt(props.source)}
      </Text>
      <Text tone="ink2">{SENDER_EXPLANATION}</Text>
      <SenderPills
        allowTestID="item-allow"
        blockTestID="item-block"
        onAllow={() => {
          judgeNewsletterSender(props.source.id, "allowed");
        }}
        onBlock={() => {
          judgeNewsletterSender(props.source.id, "blocked");
          props.onBlocked();
        }}
      />
    </Card>
  );
}

// A newsletter whose web version the parser found keeps its real url; the rest have a `newsletter:` placeholder.
const NEWSLETTER_URL_PREFIX = "newsletter:";

function EmailLinks({ url, onOpenEmail }: { url: string; onOpenEmail: () => void }) {
  const theme = useTheme();

  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.lg }}>
      <Pressable testID="item-full-email" onPress={onOpenEmail} hitSlop={8}>
        <Text variant="headline">Open the full email ›</Text>
      </Pressable>
      {url.startsWith(NEWSLETTER_URL_PREFIX) ? null : (
        <Pressable testID="item-open-original" onPress={() => void Linking.openURL(url)} hitSlop={8}>
          <Text variant="headline">Open original ›</Text>
        </Pressable>
      )}
    </View>
  );
}

function SectionTitle({ children }: { children: string }) {
  return (
    <Text variant="kicker" tone="ink2">
      {children}
    </Text>
  );
}

function TimestampChip({ timestamp, source }: { timestamp: string | null; source: SourceRow }) {
  const theme = useTheme();
  if (!timestamp) return null;

  return (
    <Pressable
      testID="timestamp"
      hitSlop={8}
      onPress={() => {
        haptic("light");
        void Linking.openURL(timestampUrl(source, timestamp));
      }}
      style={{
        backgroundColor: theme.colors.press,
        borderRadius: theme.radii.chipSmall,
        paddingHorizontal: theme.spacing.sm,
        paddingVertical: theme.spacing.xs,
      }}
    >
      <Text variant="monoLabel" tone="ink2">
        {timestamp}
      </Text>
    </Pressable>
  );
}

function SummarySections({ summary, source }: { summary: SummaryContent; source: SourceRow }) {
  const theme = useTheme();

  return (
    <>
      <View style={{ gap: theme.spacing.sm }}>
        <Text testID="source-gist" variant="readingBody">
          {summary.gist}
        </Text>
      </View>

      {summary.key_ideas.length > 0 ? (
        <View style={{ gap: theme.spacing.md }}>
          <SectionTitle>Key ideas</SectionTitle>
          {summary.key_ideas.map((item, index) => (
            <View key={index} style={{ flexDirection: "row", gap: theme.spacing.sm, alignItems: "flex-start" }}>
              <Text variant="readingBody">{index + 1}.</Text>
              <Text variant="readingBody" style={{ flex: 1 }}>
                {item.idea}
              </Text>
              <TimestampChip timestamp={item.timestamp} source={source} />
            </View>
          ))}
        </View>
      ) : null}

      {summary.numbers.length > 0 ? (
        <View style={{ gap: theme.spacing.sm }}>
          <SectionTitle>Rough numbers</SectionTitle>
          <Card testID="rough-numbers" style={{ paddingVertical: 0 }}>
            {summary.numbers.map((item, index) => (
              <View
                key={index}
                style={[
                  { flexDirection: "row", gap: theme.spacing.sm, alignItems: "flex-start", paddingVertical: theme.spacing.md },
                  index > 0 ? { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.line } : null,
                ]}
              >
                <Text style={{ flex: 1 }}>
                  {splitFacts(item.fact).map((segment, segmentIndex) => (
                    <Text key={segmentIndex} style={segment.figure ? { fontFamily: fontFamily.mono } : null}>
                      {segment.text}
                    </Text>
                  ))}
                </Text>
                <TimestampChip timestamp={item.timestamp} source={source} />
              </View>
            ))}
          </Card>
        </View>
      ) : null}
    </>
  );
}

function NoteSection({ reaction, note }: { reaction: string | null; note: string | null }) {
  const theme = useTheme();
  if (!reaction && !note) return null;

  return (
    <View style={{ gap: theme.spacing.sm }}>
      <SectionTitle>Your note</SectionTitle>
      {reaction ? <Text>{REACTION_LABELS[reaction] ?? reaction}</Text> : null}
      {note ? <Text tone="ink2">{note}</Text> : null}
    </View>
  );
}
