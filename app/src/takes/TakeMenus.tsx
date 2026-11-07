import { useRouter } from "expo-router";
import { useState } from "react";

import { openChat } from "@/ask/openChat";
import { changeTakeKind, deleteTake } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import { MenuSheet } from "@/ui/MenuSheet";

import { confirmDeleteTake } from "./prompts";
import { TAKE_KIND_LABELS, type TakeKind, type TakeWithVersions } from "./takes";

type TakeMenusProps = { take: TakeWithVersions; visible: boolean; onClose: () => void };

const KINDS: TakeKind[] = ["opinion", "talking_point"];

/** The take page's ••• menu, and the kind chooser it opens. */
export function TakeMenus({ take, visible, onClose }: TakeMenusProps) {
  const router = useRouter();
  const [kindOpen, setKindOpen] = useState(false);

  return (
    <>
      <MenuSheet
        visible={visible}
        onClose={onClose}
        items={[
          {
            label: "Ask about this",
            testID: "take-menu-ask",
            onPress: () => openChat(router, { kind: "take", id: take.id, title: take.title }),
          },
          // MenuSheet runs this after the first sheet has dismissed, so two modals are never up at once.
          { label: "Change kind", testID: "take-menu-kind", startsGroup: true, onPress: () => setKindOpen(true) },
          {
            label: "Delete take",
            testID: "take-menu-delete",
            destructive: true,
            startsGroup: true,
            onPress: () =>
              confirmDeleteTake({
                title: take.title,
                onConfirm: () => {
                  deleteTake(db, take.id);
                  haptic("success");
                  requestSync();
                },
              }),
          },
        ]}
      />
      <MenuSheet
        visible={kindOpen}
        onClose={() => setKindOpen(false)}
        items={KINDS.map((kind) => ({
          label: TAKE_KIND_LABELS[kind],
          testID: `take-kind-${kind}`,
          onPress: () => {
            changeTakeKind(db, take.id, kind);
            haptic("success");
            requestSync();
          },
        }))}
      />
    </>
  );
}
