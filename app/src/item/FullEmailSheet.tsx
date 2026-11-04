import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView } from "react-native";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { Text } from "@/theme/components/Text";
import { BottomSheet } from "@/ui/BottomSheet";
import { Markdown } from "@/ui/Markdown";

type FullEmailSheetProps = { sourceId: string; visible: boolean; onClose: () => void };
type LoadState = { status: "loading" } | { status: "offline" } | { status: "ready"; text: string };

/** The newsletter's full text, fetched on open; it is not stored on the phone. */
export function FullEmailSheet({ sourceId, visible, onClose }: FullEmailSheetProps) {
  const session = useSession();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const sessionKey = session.status === "signedIn" ? session.sessionKey : null;

  useEffect(() => {
    if (!visible) return;

    let cancelled = false;
    setState({ status: "loading" });
    apiFetch(`/sources/${sourceId}/text`, { sessionKey })
      .then((body) => {
        if (!cancelled) setState({ status: "ready", text: (body as { text: string }).text });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "offline" });
      });
    return () => {
      cancelled = true;
    };
  }, [visible, sourceId, sessionKey]);

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="full-email-sheet">
      {state.status === "loading" ? <ActivityIndicator /> : null}
      {state.status === "offline" ? <Text testID="full-email-offline">Needs a connection.</Text> : null}
      {state.status === "ready" ? (
        <ScrollView style={{ maxHeight: 520 }}>
          <Markdown text={state.text} />
        </ScrollView>
      ) : null}
    </BottomSheet>
  );
}
