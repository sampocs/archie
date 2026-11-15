import { useRouter } from "expo-router";

import { openChat } from "@/ask/openChat";
import { changeTakeKind, deleteTake } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import { MoreMenu } from "@/ui/NativeMenu";

import { confirmDeleteTake } from "./prompts";
import { TAKE_KIND_LABELS, type TakeKind, type TakeWithVersions } from "./takes";

type TakeMenusProps = { take: TakeWithVersions };

const KINDS: TakeKind[] = ["opinion", "talking_point"];

/** The take page's ••• button and its native menu: Ask about this, Change kind (a submenu of the kinds), Delete take. */
export function TakeMenus({ take }: TakeMenusProps) {
  const router = useRouter();

  return (
    <MoreMenu
      testID="take-more"
      items={[
        {
          label: "Ask about this",
          testID: "take-menu-ask",
          icon: "bubble.left.and.text.bubble.right",
          onPress: () => openChat(router, { kind: "take", id: take.id, title: take.title }),
        },
        {
          label: "Change kind",
          testID: "take-menu-kind",
          icon: "arrow.left.arrow.right",
          startsGroup: true,
          submenu: KINDS.map((kind) => ({
            label: TAKE_KIND_LABELS[kind],
            testID: `take-kind-${kind}`,
            onPress: () => {
              changeTakeKind(db, take.id, kind);
              haptic("success");
              requestSync();
            },
          })),
        },
        {
          label: "Delete take",
          testID: "take-menu-delete",
          icon: "trash",
          destructive: true,
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
  );
}
