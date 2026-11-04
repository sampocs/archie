import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView } from "react-native";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { chooseEpisode } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { BottomSheet } from "@/ui/BottomSheet";
import { haptic } from "@/ui/haptics";

type Episode = { guid: string; title: string; published: string | null; duration_s: number | null; is_current: boolean };
type LoadState = { status: "loading" } | { status: "offline" } | { status: "ready"; episodes: Episode[] };
type EpisodesSheetProps = { sourceId: string; visible: boolean; onClose: () => void };

function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

/** The feed's episodes, newest first; picking another one re-runs the source against it. */
export function EpisodesSheet({ sourceId, visible, onClose }: EpisodesSheetProps) {
  const theme = useTheme();
  const session = useSession();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const sessionKey = session.status === "signedIn" ? session.sessionKey : null;

  useEffect(() => {
    if (!visible) return;

    let cancelled = false;
    setState({ status: "loading" });
    apiFetch(`/sources/${sourceId}/episodes`, { sessionKey })
      .then((body) => {
        if (!cancelled) setState({ status: "ready", episodes: (body as { episodes: Episode[] }).episodes });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "offline" });
      });
    return () => {
      cancelled = true;
    };
  }, [visible, sourceId, sessionKey]);

  function choose(episode: Episode): void {
    if (episode.is_current) return;
    chooseEpisode(db, sourceId, episode.guid);
    haptic("success");
    requestSync();
    onClose();
  }

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="episodes-sheet">
      <Text variant="headline">Which episode?</Text>
      {state.status === "loading" ? <ActivityIndicator /> : null}
      {state.status === "offline" ? <Text testID="episodes-offline">Needs a connection.</Text> : null}
      {state.status === "ready" ? (
        <ScrollView style={{ maxHeight: 420 }}>
          {state.episodes.map((episode, index) => (
            <Pressable
              key={episode.guid}
              testID={`episode-${index}`}
              onPress={() => choose(episode)}
              style={{ paddingVertical: theme.spacing.md, gap: theme.spacing.xs }}
            >
              <Text>{episode.title}</Text>
              <Text variant="secondary" tone="ink3">
                {[
                  episode.published,
                  episode.duration_s !== null ? formatDuration(episode.duration_s) : null,
                  episode.is_current ? "Matched" : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : null}
    </BottomSheet>
  );
}
