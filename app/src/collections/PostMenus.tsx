import { Linking } from "react-native";

import {
  createCollection,
  editCollectionItemNote,
  moveCollectionItem,
  removeCollectionItem,
} from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { haptic } from "@/ui/haptics";
import type { MenuItem } from "@/ui/NativeMenu";

import type { CollectionItemRow, CollectionWithItems } from "./collections";
import { promptCollectionName, promptNote } from "./prompts";

/** A post's long-press menu: Edit note, Move to (other collections, then a new one), Open original, Remove. */
export function postMenuItems(item: CollectionItemRow, collections: CollectionWithItems[]): MenuItem[] {
  const moveTo = (collectionId: string) => {
    moveCollectionItem(db, item.id, collectionId);
    haptic("success");
    requestSync();
  };

  return [
    {
      testID: "post-menu-note",
      label: "Edit note",
      icon: "square.and.pencil",
      onPress: () =>
        promptNote({
          initialNote: item.note ?? "",
          onSubmit: (note) => {
            editCollectionItemNote(db, item.id, note);
            requestSync();
          },
        }),
    },
    {
      testID: "post-menu-move",
      label: "Move to",
      icon: "folder",
      onPress: () => {},
      submenu: [
        ...collections
          .filter((collection) => collection.id !== item.collectionId)
          .map((target) => ({ testID: `post-move-${target.id}`, label: target.name, onPress: () => moveTo(target.id) })),
        {
          testID: "post-move-new",
          label: "New collection…",
          icon: "folder.badge.plus",
          startsGroup: true,
          onPress: () =>
            promptCollectionName({
              title: "New collection",
              submitLabel: "Create",
              onSubmit: (name) => moveTo(createCollection(db, name)),
            }),
        },
      ],
    },
    {
      testID: "post-menu-open",
      label: "Open original",
      icon: "safari",
      // Opens in X, YouTube or Safari, as a tap on the post does.
      onPress: () => void Linking.openURL(item.url),
    },
    {
      testID: "post-menu-remove",
      label: "Remove",
      icon: "trash",
      destructive: true,
      onPress: () => {
        removeCollectionItem(db, item.id);
        haptic("success");
        requestSync();
      },
    },
  ];
}
