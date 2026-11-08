import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { useCallback, useState } from "react";
import { Pressable, View } from "react-native";

import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { relativeTime } from "@/ask/sections";
import { Toast } from "@/ui/Toast";
import { useNow } from "@/ui/useNow";

import { confirmFrom, confirmHeadline, confirmToast } from "./confirmations";
import { confirmSignup, dismissSignup } from "./confirmActions";
import type { LibrarySource } from "./join";

const TILE_SIZE = 30;

/** Every waiting signup confirmation as a card, plus the toast shown after one is confirmed (its card is gone by then). */
export function ConfirmCards({ confirmations }: { confirmations: LibrarySource[] }) {
  const theme = useTheme();
  const [toast, setToast] = useState<string | null>(null);
  const hideToast = useCallback(() => setToast(null), []);

  return (
    <>
      {confirmations.length > 0 ? (
        <View style={{ gap: theme.spacing.md }}>
          {confirmations.map((source) => (
            <ConfirmCard key={source.id} source={source} onConfirmed={setToast} />
          ))}
        </View>
      ) : null}
      {toast ? <Toast message={toast} onHide={hideToast} /> : null}
    </>
  );
}

function ConfirmCard({ source, onConfirmed }: { source: LibrarySource; onConfirmed: (toast: string) => void }) {
  const theme = useTheme();
  const router = useRouter();
  const now = useNow();

  async function confirm(): Promise<void> {
    await confirmSignup(source);
    onConfirmed(confirmToast(source));
  }

  return (
    <Card testID={`confirm-card-${source.id}`} style={{ gap: theme.spacing.md, padding: theme.spacing.md }}>
      <Pressable
        onPress={() => router.push({ pathname: "/source/[id]", params: { id: source.id } })}
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
            {confirmHeadline(source)}
          </Text>
          <Text variant="secondary" tone="ink3" numberOfLines={1}>
            {`${confirmFrom(source)} · ${relativeTime(source.createdAt, now)}`}
          </Text>
        </View>
      </Pressable>
      <ConfirmPills
        confirmTestID="confirm-card-confirm"
        dismissTestID="confirm-card-dismiss"
        onConfirm={() => void confirm()}
        onDismiss={() => dismissSignup(source.id)}
        indent={TILE_SIZE + theme.spacing.md}
      />
    </Card>
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
  const theme = useTheme();
  const wide = props.indent === undefined;

  return (
    <View style={{ flexDirection: "row", gap: theme.spacing.sm, paddingLeft: props.indent ?? 0 }}>
      <Pill testID={props.confirmTestID} label="Confirm" primary wide={wide} onPress={props.onConfirm} />
      <Pill testID={props.dismissTestID} label="Dismiss" wide={wide} onPress={props.onDismiss} />
    </View>
  );
}

function Pill(props: { testID: string; label: string; primary?: boolean; wide: boolean; onPress: () => void }) {
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
