import { useRouter } from "expo-router";
import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, View } from "react-native";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { useChat } from "@/ask/useChats";
import type * as schema from "@/db/schema";
import { primerMarkdown } from "@/library/primer";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { Markdown } from "@/ui/Markdown";

import { transcriptMarkdown } from "./chatTranscript";

type SourceRow = typeof schema.sources.$inferSelect;
type ArtifactRow = typeof schema.artifacts.$inferSelect;
type Version = "archie" | "original";
type OriginalState = { status: "loading" } | { status: "offline" } | { status: "ready"; markdown: string };

const VERSION_LABELS: Record<Version, string> = { archie: "Archie's version", original: "See original" };
const VERSIONS: readonly Version[] = ["archie", "original"];

/**
 * A chat item's page body: Archie's version (the cheat sheet, its primer) first, or the original (the chat's
 * transcript, read-only) with Continue in Ask while that chat still exists.
 */
export function ChatItemBody({ source, primer }: { source: SourceRow; primer: ArtifactRow | undefined }) {
  const theme = useTheme();
  const [version, setVersion] = useState<Version>("archie");

  return (
    <View style={{ gap: theme.spacing.lg }}>
      <View style={{ flexDirection: "row", backgroundColor: theme.colors.press, borderRadius: 10, padding: 2 }}>
        {VERSIONS.map((option) => (
          <Pressable
            key={option}
            testID={`chat-item-${option}`}
            accessibilityRole="tab"
            accessibilityState={{ selected: option === version }}
            onPress={() => {
              if (option === version) return;
              haptic("selection");
              setVersion(option);
            }}
            style={[
              { flex: 1, alignItems: "center", paddingVertical: theme.spacing.sm, borderRadius: 8 },
              option === version ? { backgroundColor: theme.colors.surface } : null,
              option === version && theme.scheme === "light" ? styles.shadow : null,
            ]}
          >
            <Text variant="secondary" tone={option === version ? "ink" : "ink3"}>
              {VERSION_LABELS[option]}
            </Text>
          </Pressable>
        ))}
      </View>
      {version === "archie" ? (
        primer ? (
          <Markdown text={primerMarkdown(primer.content)} />
        ) : (
          <Text testID="chat-item-pending" tone="ink2">
            Archie's version is on its way
          </Text>
        )
      ) : (
        <Original source={source} />
      )}
    </View>
  );
}

/**
 * The transcript saved with the item, fetched on open (it is not stored on the phone). Without a connection it is
 * rebuilt from the chat's synced messages while the chat still exists.
 */
function Original({ source }: { source: SourceRow }) {
  const theme = useTheme();
  const router = useRouter();
  const { sessionKey } = useSession();
  const conversationId = source.chatConversationId;
  const { conversation, messages } = useChat(conversationId ?? "");
  const chatLives = conversation !== null && conversation.deletedAt === null;
  const [state, setState] = useState<OriginalState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    apiFetch(`/sources/${source.id}/text`, { sessionKey })
      .then((body) => {
        if (!cancelled) setState({ status: "ready", markdown: (body as { text: string }).text });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "offline" });
      });
    return () => {
      cancelled = true;
    };
  }, [source.id, sessionKey]);

  const fallback = chatLives && messages.length > 0 ? transcriptMarkdown(messages) : null;
  const markdown = state.status === "ready" ? state.markdown : state.status === "offline" ? fallback : null;

  return (
    <View testID="chat-item-original" style={{ gap: theme.spacing.lg }}>
      {state.status === "loading" ? <ActivityIndicator /> : null}
      {markdown !== null ? <Markdown text={markdown} /> : null}
      {state.status === "offline" && markdown === null ? (
        <Text testID="chat-item-original-offline" tone="ink2">
          Needs a connection.
        </Text>
      ) : null}
      {chatLives && conversationId ? (
        <Button
          testID="chat-item-continue"
          variant="secondary"
          label="Continue in Ask"
          onPress={() => router.push({ pathname: "/ask/[id]", params: { id: conversationId } })}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  shadow: { shadowColor: "#0E0E0C", shadowOpacity: 0.1, shadowRadius: 2, shadowOffset: { width: 0, height: 1 } },
});
