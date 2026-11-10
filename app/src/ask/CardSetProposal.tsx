import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";

import { UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { isConflict, isNotFound } from "@/edits/api";
import { NETWORK_FAILED } from "@/edits/proposalState";
import { requestSync } from "@/sync/useSync";
import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { fontFamily } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import { discardCardSet, saveCardSet } from "./api";
import {
  allKept,
  cardSetBlock,
  hasCheatSheet,
  keptIndices,
  opensByGoingBack,
  pageLabel,
  saveLabel,
  savedToast,
  stepPage,
  toggleKept,
  type CardSetView,
  type ProposedCard,
} from "./cardSets";
import { CheatSheetSheet } from "./CheatSheetSheet";
import { useCardSetMode, useCardSetRow } from "./useCardSets";

type CardSetProposalProps = {
  cardSet: CardSetView;
  // False while the answer is still streaming: the set is stored only when the answer is.
  ready: boolean;
  online: boolean;
  // A newer set is in the live answer, so this one is about to be replaced.
  replacedLive?: boolean;
  // The chat already saved its Library item, so Save updates it.
  updating: boolean;
  onToast: (message: string) => void;
};

const STRUCK = 0.45;
const CARD_SET_GONE = "This card set is gone";

/**
 * A card set Ask proposed: the cheat-sheet line (none for a note's set), the cards one at a time (or all in a list) with a Keep tick each, and
 * one footer row with Save K / Update K and Discard. Once it is decided it shrinks to how it ended.
 */
export function CardSetProposal({ cardSet: streamed, ready, online, replacedLive, updating, onToast }: CardSetProposalProps) {
  const theme = useTheme();
  const router = useRouter();
  const { fromNote } = useLocalSearchParams<{ fromNote?: string }>();
  const { sessionKey } = useSession();
  // The stored row wins once the phone has it: it carries what Save or Discard did.
  const cardSet = useCardSetRow(streamed.id) ?? streamed;
  const block = cardSetBlock(cardSet, replacedLive);
  const [kept, setKept] = useState(() => allKept(cardSet.cards.length));
  const [page, setPage] = useState(0);
  const [mode, setMode] = useCardSetMode();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const id = cardSet.id;

  if (block.kind === "collapsed") return <Collapsed testID={`card-set-${id}`} left={block.left} right={block.right} />;

  function act(send: (sessionKey: string) => Promise<unknown>, done: string | null): void {
    if (!sessionKey || busy) return;
    setBusy(true);
    send(sessionKey)
      .then(() => {
        haptic("success");
        if (done) onToast(done);
      })
      .catch((error) => {
        if (error instanceof UnauthorizedError) {
          void clearSession();
          return;
        }
        // A 409 means the server already moved the set on; the sync below brings its state.
        if (isNotFound(error)) onToast(CARD_SET_GONE);
        else if (!isConflict(error)) onToast(NETWORK_FAILED);
      })
      .finally(() => {
        setBusy(false);
        requestSync();
      });
  }

  const keptCount = keptIndices(kept).length;
  const sheet = (
    <CheatSheetSheet
      title={cardSet.title}
      markdown={cardSet.cheatSheet}
      visible={sheetOpen}
      onClose={() => setSheetOpen(false)}
    />
  );
  const cheatSheetLine = hasCheatSheet(cardSet) ? (
    <CheatSheetLine title={cardSet.title} onPress={() => setSheetOpen(true)} />
  ) : null;

  if (block.kind === "saved") {
    const itemId = block.itemId;
    return (
      <Card testID={`card-set-${id}`} style={{ gap: theme.spacing.sm, padding: theme.spacing.md }}>
        {cheatSheetLine}
        <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md }}>
          <Text testID="card-set-status" variant="secondary" style={{ color: theme.signals.gotIt, fontFamily: fontFamily.semibold }}>
            {block.line}
          </Text>
          {itemId ? (
            <Pressable
              testID="card-set-open"
              hitSlop={8}
              onPress={() =>
                opensByGoingBack(fromNote, itemId)
                  ? router.back()
                  : router.push({ pathname: "/source/[id]", params: { id: itemId } })
              }
            >
              <Text variant="secondary" tone="ink2" style={{ textDecorationLine: "underline", fontFamily: fontFamily.semibold }}>
                Open
              </Text>
            </Pressable>
          ) : null}
        </View>
        {sheet}
      </Card>
    );
  }

  const total = cardSet.cards.length;
  const toggle = (index: number) => {
    haptic("selection");
    setKept((current) => toggleKept(current, index));
  };

  return (
    <Card testID={`card-set-${id}`} style={{ gap: theme.spacing.sm, padding: theme.spacing.md }}>
      {cheatSheetLine}
      {mode === "pager" && total > 0 ? (
        <CardFace card={cardSet.cards[page]} index={page} kept={kept[page]} onToggle={() => toggle(page)} />
      ) : null}
      {mode === "list" ? (
        <View testID="card-set-list" style={{ gap: theme.spacing.sm }}>
          {cardSet.cards.map((card, index) => (
            <ListRow key={index} card={card} index={index} kept={kept[index]} onToggle={() => toggle(index)} />
          ))}
        </View>
      ) : null}
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        {mode === "pager" ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md }}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.xs }}>
              <Pressable testID="card-set-prev" hitSlop={8} disabled={page === 0} onPress={() => setPage(stepPage(page, -1, total))}>
                <Text variant="monoLabel" tone={page === 0 ? "ink3" : "ink2"}>
                  ‹
                </Text>
              </Pressable>
              <Text testID="card-set-page" variant="monoLabel" tone="ink2">
                {pageLabel(page, total)}
              </Text>
              <Pressable
                testID="card-set-next"
                hitSlop={8}
                disabled={page >= total - 1}
                onPress={() => setPage(stepPage(page, 1, total))}
              >
                <Text variant="monoLabel" tone={page >= total - 1 ? "ink3" : "ink2"}>
                  ›
                </Text>
              </Pressable>
            </View>
            <FooterLink testID="card-set-see-all" label="See all" onPress={() => setMode("list")} />
          </View>
        ) : (
          <FooterLink testID="card-set-one-at-a-time" label="One at a time" onPress={() => setMode("pager")} />
        )}
        {online ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}>
            <Pressable
              testID="card-set-save"
              disabled={!ready || busy || keptCount === 0}
              onPress={() => act((key) => saveCardSet({ proposalId: id, kept: keptIndices(kept), sessionKey: key }), savedToast(cardSet))}
              style={{
                backgroundColor: theme.colors.chrome,
                borderRadius: theme.radii.chip,
                paddingHorizontal: theme.spacing.md,
                paddingVertical: 6,
                opacity: !ready || busy || keptCount === 0 ? 0.4 : 1,
              }}
            >
              <Text variant="secondary" tone="onChrome" style={{ fontFamily: fontFamily.semibold }}>
                {saveLabel(keptCount, updating)}
              </Text>
            </Pressable>
            <Pressable
              testID="card-set-discard"
              accessibilityLabel="Discard"
              hitSlop={10}
              disabled={!ready || busy}
              onPress={() => act((key) => discardCardSet({ proposalId: id, sessionKey: key }), null)}
              style={{ opacity: !ready || busy ? 0.4 : 1 }}
            >
              <Text tone="ink3" style={{ fontSize: 18 }}>
                ×
              </Text>
            </Pressable>
          </View>
        ) : (
          <Text testID="card-set-offline" variant="secondary" tone="ink3">
            Needs a connection
          </Text>
        )}
      </View>
      {sheet}
    </Card>
  );
}

function CheatSheetLine({ title, onPress }: { title: string; onPress: () => void }) {
  const theme = useTheme();
  return (
    <Pressable
      testID="card-set-cheat-sheet"
      onPress={onPress}
      hitSlop={6}
      style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.sm }}
    >
      <Text numberOfLines={1} style={{ flex: 1, fontFamily: fontFamily.semibold }}>
        {`▤ Cheat sheet · ${title}`}
      </Text>
      <Text tone="ink3">›</Text>
    </Pressable>
  );
}

/** One card of the pager: CARD n with its Keep tick, the question, then the answer under a dashed rule. */
function CardFace({ card, index, kept, onToggle }: { card: ProposedCard; index: number; kept: boolean; onToggle: () => void }) {
  const theme = useTheme();
  return (
    <View
      testID="card-set-card"
      style={{
        borderWidth: 1,
        borderColor: theme.colors.line,
        borderRadius: theme.radii.chip,
        padding: theme.spacing.md,
        gap: theme.spacing.sm,
      }}
    >
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text variant="monoLabel" tone="ink3">{`Card ${index + 1}`}</Text>
        <Pressable
          testID={`card-set-keep-${index}`}
          accessibilityRole="checkbox"
          accessibilityState={{ checked: kept }}
          hitSlop={10}
          onPress={onToggle}
          style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.xs }}
        >
          <Tick kept={kept} />
          <Text variant="secondary" style={{ fontFamily: fontFamily.semibold, color: kept ? theme.signals.gotIt : theme.colors.ink3 }}>
            Keep
          </Text>
        </Pressable>
      </View>
      <View style={{ gap: theme.spacing.sm, opacity: kept ? 1 : STRUCK }}>
        <Text style={{ fontFamily: fontFamily.semibold, textDecorationLine: kept ? "none" : "line-through" }}>
          {card.question}
        </Text>
        <DashedRule />
        <Text variant="secondary" tone="ink2">
          {card.answer}
        </Text>
      </View>
    </View>
  );
}

/** One numbered row of See all; tapping anywhere on it flips its tick. */
function ListRow({ card, index, kept, onToggle }: { card: ProposedCard; index: number; kept: boolean; onToggle: () => void }) {
  const theme = useTheme();
  return (
    <Pressable
      testID={`card-set-keep-${index}`}
      accessibilityRole="checkbox"
      accessibilityState={{ checked: kept }}
      onPress={onToggle}
      style={{ flexDirection: "row", gap: theme.spacing.sm, alignItems: "flex-start" }}
    >
      <View style={{ paddingTop: 2 }}>
        <Tick kept={kept} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Text variant="secondary" tone={kept ? "ink" : "ink3"}>
          <Text variant="monoLabel" tone="ink3">{`${index + 1}  `}</Text>
          <Text style={{ fontFamily: fontFamily.semibold, textDecorationLine: kept ? "none" : "line-through" }} tone={kept ? "ink" : "ink3"}>
            {card.question}
          </Text>
        </Text>
        <Text variant="secondary" tone={kept ? "ink2" : "ink3"}>
          {card.answer}
        </Text>
      </View>
    </Pressable>
  );
}

function Tick({ kept }: { kept: boolean }) {
  const theme = useTheme();
  return (
    <View
      style={{
        width: 14,
        height: 14,
        borderRadius: 4,
        borderWidth: 1.5,
        borderColor: kept ? theme.signals.gotIt : theme.colors.ink3,
        backgroundColor: kept ? theme.signals.gotIt : "transparent",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {kept ? <Text style={{ color: theme.colors.onDomain, fontSize: 9, lineHeight: 11 }}>✓</Text> : null}
    </View>
  );
}

// iOS draws a dashed border only around a whole box, so the rule is a one-point-high dashed box.
function DashedRule() {
  const theme = useTheme();
  return <View style={{ height: 1, borderWidth: 1, borderRadius: 1, borderStyle: "dashed", borderColor: theme.colors.line }} />;
}

function FooterLink({ testID, label, onPress }: { testID: string; label: string; onPress: () => void }) {
  return (
    <Pressable testID={testID} hitSlop={8} onPress={onPress}>
      <Text variant="secondary" tone="ink2" style={{ fontFamily: fontFamily.semibold }}>
        {label}
      </Text>
    </Pressable>
  );
}

/**
 * A set that is over without a save, one line: "Earlier proposal · Replaced" or "Cheat sheet · … · Discarded"
 * ("Cards · … · Discarded" for a note's set).
 */
function Collapsed({ testID, left, right }: { testID: string; left: string; right: string }) {
  const theme = useTheme();
  return (
    <View
      testID={testID}
      style={{
        flexDirection: "row",
        justifyContent: "space-between",
        gap: theme.spacing.md,
        borderWidth: 1,
        borderColor: theme.colors.line,
        backgroundColor: theme.colors.surface,
        borderRadius: theme.radii.chip,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
      }}
    >
      <Text variant="secondary" tone="ink3" numberOfLines={1} style={{ flexShrink: 1 }}>
        {left}
      </Text>
      <Text testID="card-set-status" variant="secondary" tone="ink3">
        {right}
      </Text>
    </View>
  );
}
