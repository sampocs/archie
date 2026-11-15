import { useRouter } from "expo-router";
import { Pressable, View } from "react-native";

import { confirmDeleteCollection, promptCollectionName } from "@/collections/prompts";
import type { CollectionWithItems } from "@/collections/collections";
import { useCollectionsData } from "@/collections/useCollectionsData";
import { db } from "@/db/client";
import { createCollection, deleteCollection, renameCollection } from "@/db/actions";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { LongPressMenu, type MenuItem } from "@/ui/NativeMenu";

import { CollectionTile } from "./CollectionTile";

const NEW_TILE_MIN_HEIGHT = 140;

/** Saved's Collections section: a tile per collection, then a "New collection" tile; long-press opens Rename/Delete. */
export function CollectionsSection() {
  const theme = useTheme();
  const router = useRouter();
  const collections = useCollectionsData();

  const startNewCollection = () =>
    promptCollectionName({
      title: "New collection",
      submitLabel: "Create",
      onSubmit: (name) => {
        createCollection(db, name);
        haptic("success");
        requestSync();
      },
    });

  return (
    <View testID="saved-collections" style={{ gap: theme.spacing.sm }}>
      <Text variant="monoLabel" tone="ink3">
        {`Collections · ${collections.length}`}
      </Text>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
        {collections.map((collection) => (
          <View key={collection.id} style={{ width: "48.5%" }}>
            <LongPressMenu items={collectionMenuItems(collection)}>
              <CollectionTile
                collection={collection}
                onPress={() => {
                  haptic("light");
                  router.push({ pathname: "/collection/[id]", params: { id: collection.id } });
                }}
              />
            </LongPressMenu>
          </View>
        ))}

        <Pressable
          testID="collection-new-tile"
          onPress={startNewCollection}
          style={{
            width: "48.5%",
            minHeight: NEW_TILE_MIN_HEIGHT,
            borderWidth: 1.5,
            borderColor: theme.colors.cardEdge,
            borderRadius: 16,
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Text variant="headline" tone="ink2">
            ＋ New collection
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

/** A tile's long-press menu: Rename, then Delete collection, which asks first. */
function collectionMenuItems(collection: CollectionWithItems): MenuItem[] {
  return [
    {
      label: "Rename",
      testID: "collection-menu-rename",
      icon: "pencil",
      onPress: () =>
        promptCollectionName({
          title: "Rename collection",
          submitLabel: "Save",
          initialName: collection.name,
          onSubmit: (name) => {
            renameCollection(db, collection.id, name);
            requestSync();
          },
        }),
    },
    {
      label: "Delete collection",
      testID: "collection-menu-delete",
      icon: "trash",
      destructive: true,
      onPress: () =>
        confirmDeleteCollection({
          name: collection.name,
          count: collection.items.length,
          onConfirm: () => {
            deleteCollection(db, collection.id);
            haptic("success");
            requestSync();
          },
        }),
    },
  ];
}
