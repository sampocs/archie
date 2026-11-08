import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import { Pressable, View } from "react-native";

import { UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import { isConflict, sendEditAction, type EditAction } from "./api";
import { editLines, parseContent } from "./content";
import { foldUnchanged, lineDiff, type ShownLine } from "./diff";
import { KICKERS, NETWORK_FAILED, STATUS_LINES, shownStatus, targetHref, UNDO_CONFLICT } from "./proposalState";
import type { ProposalView } from "./types";
import { useProposalRow } from "./useProposals";
import { useTargetVersions } from "./useTargetVersions";

type EditProposalCardProps = {
  proposal: ProposalView;
  // False while the answer is still streaming: the proposal is stored only when the answer is.
  ready: boolean;
  online: boolean;
  // A newer proposal for the same target is in the live answer, so this one is about to be superseded.
  supersededLive?: boolean;
  onToast: (message: string) => void;
};

/** One edit Ask proposed: what changes, as a diff, with Apply / Discard, then Applied · Undo or how it ended. */
export function EditProposalCard({ proposal: streamed, ready, online, supersededLive, onToast }: EditProposalCardProps) {
  const theme = useTheme();
  const router = useRouter();
  const { sessionKey } = useSession();
  const [busy, setBusy] = useState(false);

  // The stored row wins once the phone has it: it carries what Apply, Undo or Discard did.
  const proposal = useProposalRow(streamed.id) ?? streamed;
  const { current } = useTargetVersions(proposal.targetKind, proposal.targetId);
  const status = shownStatus(proposal, current, supersededLive);
  const lines = useMemo(() => {
    const kind = proposal.targetKind;
    const before = editLines(kind, parseContent(kind, proposal.before));
    return foldUnchanged(lineDiff(before, editLines(kind, parseContent(kind, proposal.after))));
  }, [proposal.targetKind, proposal.before, proposal.after]);

  function act(action: EditAction): void {
    if (!sessionKey || busy) return;
    setBusy(true);
    sendEditAction({ proposalId: proposal.id, action, sessionKey })
      .then(() => haptic("success"))
      .catch((error) => {
        if (error instanceof UnauthorizedError) {
          void clearSession();
          return;
        }
        // Any other 409 means the server already moved the proposal on; the sync below brings its state.
        if (action === "undo" && isConflict(error)) onToast(UNDO_CONFLICT);
        else if (!isConflict(error)) onToast(NETWORK_FAILED);
      })
      .finally(() => {
        setBusy(false);
        requestSync();
      });
  }

  const id = proposal.id;
  return (
    <Card testID={`edit-proposal-${id}`} style={{ gap: theme.spacing.sm }}>
      <Text variant="kicker" tone="ink2">
        {KICKERS[proposal.targetKind]}
      </Text>
      <Pressable
        testID={`edit-title-${id}`}
        hitSlop={8}
        onPress={() => router.push(targetHref(proposal.targetKind, proposal.targetId))}
      >
        <Text variant="headline">{`${proposal.title} ›`}</Text>
      </Pressable>
      <Text tone="ink2">{proposal.description}</Text>
      <View testID={`edit-diff-${id}`} style={{ gap: theme.spacing.xs }}>
        {lines.map((line, index) => (
          <DiffRow key={index} line={line} />
        ))}
      </View>
      {status === "proposed" ? (
        online ? (
          <View style={{ flexDirection: "row", gap: theme.spacing.sm }}>
            <View style={{ flex: 1 }}>
              <Button testID={`edit-apply-${id}`} label="Apply" disabled={!ready || busy} onPress={() => act("apply")} />
            </View>
            <View style={{ flex: 1 }}>
              <Button
                testID={`edit-discard-${id}`}
                variant="secondary"
                label="Discard"
                disabled={!ready || busy}
                onPress={() => act("discard")}
              />
            </View>
          </View>
        ) : (
          <Text testID={`edit-status-${id}`} tone="ink3">
            Needs a connection
          </Text>
        )
      ) : (
        <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md }}>
          <Text testID={`edit-status-${id}`} tone="ink2">
            {STATUS_LINES[status]}
          </Text>
          {status === "applied" && online ? (
            <Pressable testID={`edit-undo-${id}`} hitSlop={8} disabled={busy} onPress={() => act("undo")}>
              <Text variant="headline">Undo</Text>
            </Pressable>
          ) : null}
        </View>
      )}
    </Card>
  );
}

function DiffRow({ line }: { line: ShownLine }) {
  const theme = useTheme();
  if (line.kind === "gap") {
    return (
      <Text variant="secondary" tone="ink3">
        {`⋯ ${line.count} unchanged`}
      </Text>
    );
  }
  if (line.kind === "same") return <Text tone="ink2">{line.text}</Text>;

  const removed = line.kind === "removed";
  return (
    <Text
      style={{
        color: removed ? theme.signals.missed : theme.signals.gotIt,
        textDecorationLine: removed ? "line-through" : "none",
      }}
    >
      {`${removed ? "−" : "+"} ${line.text}`}
    </Text>
  );
}
