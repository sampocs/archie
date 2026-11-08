import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { Fragment, useCallback, useState, type ReactNode } from "react";
import { Pressable, View } from "react-native";

import type { SenderStatus } from "@/db/actions";
import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { relativeTime } from "@/ask/sections";
import { Toast } from "@/ui/Toast";
import { useNow } from "@/ui/useNow";

import { confirmFrom, confirmHeadline, confirmToast } from "./confirmations";
import { confirmSignup, dismissSignup } from "./confirmActions";
import type { LibrarySource } from "./join";
import { judgeNewsletterSender } from "./senderActions";
import { senderFrom, senderHeadline, senderSubject, senderToast } from "./senders";

const TILE_SIZE = 30;

/** Every waiting signup confirmation as a card, plus the toast shown after one is confirmed (its card is gone by then). */
export function ConfirmCards({ confirmations }: { confirmations: LibrarySource[] }) {
  return (
    <NoticeCards
      sources={confirmations}
      renderCard={(source, showToast) => <ConfirmCard source={source} onConfirmed={showToast} />}
    />
  );
}

/** Every newsletter waiting on its sender's Allow or Block as a card, plus the toast shown after one is decided. */
export function SenderCards({ pendingSenders }: { pendingSenders: LibrarySource[] }) {
  return (
    <NoticeCards
      sources={pendingSenders}
      renderCard={(source, showToast) => <SenderCard source={source} onJudged={showToast} />}
    />
  );
}

/** A stack of cards, one per source, with the toast a card raises once it has done its job (and is gone). */
function NoticeCards(props: {
  sources: LibrarySource[];
  renderCard: (source: LibrarySource, showToast: (message: string) => void) => ReactNode;
}) {
  const theme = useTheme();
  const [toast, setToast] = useState<string | null>(null);
  const hideToast = useCallback(() => setToast(null), []);

  return (
    <>
      {props.sources.length > 0 ? (
        <View style={{ gap: theme.spacing.md }}>
          {props.sources.map((source) => (
            <Fragment key={source.id}>{props.renderCard(source, setToast)}</Fragment>
          ))}
        </View>
      ) : null}
      {toast ? <Toast message={toast} onHide={hideToast} /> : null}
    </>
  );
}

function ConfirmCard({ source, onConfirmed }: { source: LibrarySource; onConfirmed: (toast: string) => void }) {
  const now = useNow();

  async function confirm(): Promise<void> {
    if (await confirmSignup(source)) onConfirmed(confirmToast(source));
  }

  return (
    <NoticeCard
      testID={`confirm-card-${source.id}`}
      sourceId={source.id}
      headline={confirmHeadline(source)}
      secondary={`${confirmFrom(source)} · ${relativeTime(source.createdAt, now)}`}
      pills={(indent) => (
        <ConfirmPills
          confirmTestID="confirm-card-confirm"
          dismissTestID="confirm-card-dismiss"
          onConfirm={() => void confirm()}
          onDismiss={() => dismissSignup(source.id)}
          indent={indent}
        />
      )}
    />
  );
}

function SenderCard({ source, onJudged }: { source: LibrarySource; onJudged: (toast: string) => void }) {
  const now = useNow();

  function judge(status: SenderStatus): void {
    judgeNewsletterSender(source.id, status);
    onJudged(senderToast(source, status));
  }

  return (
    <NoticeCard
      testID={`sender-card-${source.id}`}
      sourceId={source.id}
      headline={senderHeadline(source)}
      secondary={senderFrom(source, relativeTime(source.createdAt, now))}
      tertiary={senderSubject(source)}
      pills={(indent) => (
        <SenderPills
          allowTestID="sender-card-allow"
          blockTestID="sender-card-block"
          onAllow={() => judge("allowed")}
          onBlock={() => judge("blocked")}
          indent={indent}
        />
      )}
    />
  );
}

/** The card shell the Library's notice cards share: a mail tile and up to three lines (tap opens the item), then pills. */
function NoticeCard(props: {
  testID: string;
  sourceId: string;
  headline: string;
  secondary: string;
  // A faint third line, left out when null or absent.
  tertiary?: string | null;
  // The pills, told how far to indent so they line up under the text.
  pills: (indent: number) => ReactNode;
}) {
  const theme = useTheme();
  const router = useRouter();

  return (
    <Card testID={props.testID} style={{ gap: theme.spacing.md, padding: theme.spacing.md }}>
      <Pressable
        onPress={() => router.push({ pathname: "/source/[id]", params: { id: props.sourceId } })}
        style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md }}
      >
        <View
          style={{
            width: TILE_SIZE,
            height: TILE_SIZE,
            borderRadius: theme.radii.chipSmall,
            backgroundColor: theme.colors.chrome,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Ionicons name="mail-outline" size={18} color={theme.colors.onChrome} />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <Text variant="headline" numberOfLines={2}>
            {props.headline}
          </Text>
          <Text variant="secondary" tone="ink3" numberOfLines={1}>
            {props.secondary}
          </Text>
          {props.tertiary ? (
            <Text variant="secondary" tone="ink3" numberOfLines={1}>
              {props.tertiary}
            </Text>
          ) : null}
        </View>
      </Pressable>
      {props.pills(TILE_SIZE + theme.spacing.md)}
    </Card>
  );
}

type PillButton = { testID: string; label: string; onPress: () => void };

/** A primary and a secondary pill. `indent` lines them up under a card's text, or leave it out to fill the row. */
function ActionPills(props: { primary: PillButton; secondary: PillButton; indent?: number }) {
  const theme = useTheme();
  const wide = props.indent === undefined;

  return (
    <View style={{ flexDirection: "row", gap: theme.spacing.sm, paddingLeft: props.indent ?? 0 }}>
      <Pill {...props.primary} primary wide={wide} />
      <Pill {...props.secondary} wide={wide} />
    </View>
  );
}

type ConfirmPillsProps = {
  confirmTestID: string;
  dismissTestID: string;
  onConfirm: () => void;
  onDismiss: () => void;
  // Left padding so the pills line up under the text (the card), or none when they fill the row (the item page).
  indent?: number;
};

/** The Confirm (primary) and Dismiss (secondary) pills shared by the Library card and the item page. */
export function ConfirmPills(props: ConfirmPillsProps) {
  return (
    <ActionPills
      primary={{ testID: props.confirmTestID, label: "Confirm", onPress: props.onConfirm }}
      secondary={{ testID: props.dismissTestID, label: "Dismiss", onPress: props.onDismiss }}
      indent={props.indent}
    />
  );
}

type SenderPillsProps = {
  allowTestID: string;
  blockTestID: string;
  onAllow: () => void;
  onBlock: () => void;
  indent?: number;
};

/** The Allow (primary) and Block (secondary) pills shared by the Library sender card and the item page. */
export function SenderPills(props: SenderPillsProps) {
  return (
    <ActionPills
      primary={{ testID: props.allowTestID, label: "Allow", onPress: props.onAllow }}
      secondary={{ testID: props.blockTestID, label: "Block", onPress: props.onBlock }}
      indent={props.indent}
    />
  );
}

function Pill(props: PillButton & { primary?: boolean; wide: boolean }) {
  const theme = useTheme();

  return (
    <Pressable
      testID={props.testID}
      onPress={props.onPress}
      hitSlop={6}
      style={{
        flex: props.wide ? 1 : undefined,
        alignItems: "center",
        paddingHorizontal: theme.spacing.lg,
        paddingVertical: theme.spacing.sm,
        borderRadius: 999,
        backgroundColor: props.primary ? theme.colors.chrome : theme.colors.press,
      }}
    >
      <Text variant="secondary" tone={props.primary ? "onChrome" : "ink"} style={{ fontWeight: "600" }}>
        {props.label}
      </Text>
    </Pressable>
  );
}
