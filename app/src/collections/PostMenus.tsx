import { useState } from "react";

import { editCollectionItemNote, moveCollectionItem, removeCollectionItem } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import { MenuSheet, type MenuItem } from "@/ui/MenuSheet";

import type { CollectionItemRow, CollectionWithItems } from "./collections";
import { promptNote } from "./prompts";

type PostMenusProps = { item: CollectionItemRow | null; collections: CollectionWithItems[]; onClose: () => void };

/** The long-press menu for a post, and the "Move to…" list it opens. */
export function PostMenus({ item, collections, onClose }: PostMenusProps) {
  // The move list opens from the first sheet's action, which MenuSheet runs after dismissal: never two modals at once.
  const [moving, setMoving] = useState<CollectionItemRow | null>(null);
  const targets = item ? collections.filter((collection) => collection.id !== item.collectionId) : [];

  const items: MenuItem[] = item
    ? [
        {
          testID: "post-menu-note",
          label: "Edit note",
          onPress: () =>
            promptNote({
              initialNote: item.note ?? "",
              onSubmit: (note) => {
                editCollectionItemNote(db, item.id, note);
                requestSync();
              },
            }),
        },
        ...(targets.length > 0
          ? [{ testID: "post-menu-move", label: "Move to…", onPress: () => setMoving(item) }]
          : []),
        {
          testID: "post-menu-remove",
          label: "Remove",
          destructive: true,
          startsGroup: true,
          onPress: () => {
            removeCollectionItem(db, item.id);
            haptic("success");
            requestSync();
          },
        },
      ]
    : [];

  const moveItems: MenuItem[] = moving
    ? collections
        .filter((collection) => collection.id !== moving.collectionId)
        .map((target) => ({
          testID: `post-move-${target.id}`,
          label: target.name,
          onPress: () => {
            moveCollectionItem(db, moving.id, target.id);
            haptic("success");
            requestSync();
          },
        }))
    : [];

  return (
    <>
      <MenuSheet visible={item !== null} onClose={onClose} items={items} />
      <MenuSheet visible={moving !== null} onClose={() => setMoving(null)} items={moveItems} />
    </>
  );
}
