import * as Network from "expo-network";
import { useEffect, useState } from "react";
import { Pressable, ScrollView, View } from "react-native";

import { UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { BottomSheet } from "@/ui/BottomSheet";
import { haptic } from "@/ui/haptics";
import { useNow } from "@/ui/useNow";

import { restoreVersion } from "./api";
import type { EditTargetKind } from "./types";
import { useTargetVersions } from "./useTargetVersions";
import { VersionPreview } from "./VersionPreview";
import { sheetTitle, versionRowDetail, versionRowTitle } from "./versionRows";

type VersionsSheetProps = {
  target: { kind: EditTargetKind; id: string } | null;
  visible: boolean;
  onClose: () => void;
  // Called with the version that was copied; the page shows "Restored version N".
  onRestored: (version: number) => void;
};

const MAX_SHEET_HEIGHT = 560;

/** A target's versions, newest first; tap one to read it and restore it as the newest version. */
export function VersionsSheet({ target, visible, onClose, onRestored }: VersionsSheetProps) {
  const theme = useTheme();
  const now = useNow();
  const { sessionKey } = useSession();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  const { entries } = useTargetVersions(target?.kind ?? null, target?.id ?? null);
  const [shown, setShown] = useState<number | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [failed, setFailed] = useState(false);

  // Each opening starts at the list.
  useEffect(() => {
    if (visible) {
      setShown(null);
      setFailed(false);
    }
  }, [visible]);

  if (!target) return null;
  const entry = entries.find((candidate) => candidate.version === shown) ?? null;

  function restore(version: number): void {
    if (!target || !sessionKey) return;
    setRestoring(true);
    setFailed(false);
    restoreVersion({ targetKind: target.kind, targetId: target.id, version, sessionKey })
      .then(() => {
        haptic("success");
        requestSync();
        onClose();
        onRestored(version);
      })
      .catch((error) => {
        if (error instanceof UnauthorizedError) void clearSession();
        setFailed(true);
      })
      .finally(() => setRestoring(false));
  }

  return (
    <BottomSheet testID="versions-sheet" visible={visible} onClose={onClose}>
      <Text variant="headline">{sheetTitle(target.kind)}</Text>
      <ScrollView style={{ maxHeight: MAX_SHEET_HEIGHT }} contentContainerStyle={{ gap: theme.spacing.md }}>
        {entry ? (
          <View testID="version-preview" style={{ gap: theme.spacing.md }}>
            <Text variant="secondary" tone="ink3">
              {`${versionRowTitle(entry, now)} · ${versionRowDetail(entry)}`}
            </Text>
            <VersionPreview kind={target.kind} content={entry.content} />
          </View>
        ) : (
          entries.map((candidate) => (
            <Pressable
              key={candidate.version}
              testID={`version-row-${candidate.version}`}
              onPress={() => setShown(candidate.version)}
              style={{ gap: theme.spacing.xs }}
            >
              <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text>{versionRowTitle(candidate, now)}</Text>
                {candidate.current ? (
                  <Text testID={`version-current-${candidate.version}`} variant="secondary" tone="ink2">
                    Current
                  </Text>
                ) : null}
              </View>
              <Text variant="secondary" tone="ink3">
                {versionRowDetail(candidate)}
              </Text>
            </Pressable>
          ))
        )}
      </ScrollView>
      {entry ? (
        <View style={{ gap: theme.spacing.sm }}>
          {entry.current ? null : online ? (
            <Button
              testID="version-restore"
              label="Restore this version"
              disabled={restoring}
              onPress={() => restore(entry.version)}
            />
          ) : (
            <Text testID="version-offline" tone="ink3">
              Restoring needs a connection
            </Text>
          )}
          {failed ? <Text tone="ink2">Couldn't reach Archie. Try again.</Text> : null}
          <Button testID="version-back" variant="secondary" label="Back" onPress={() => setShown(null)} />
        </View>
      ) : null}
    </BottomSheet>
  );
}
