import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, View } from "react-native";

import {
  confirmDeleteCollection,
  promptCollectionName,
} from "@/collections/prompts";
import type { CollectionWithItems } from "@/collections/collections";
import { useCollectionsData } from "@/collections/useCollectionsData";
import { db } from "@/db/client";
import { createCollection, deleteCollection, renameCollection } from "@/db/actions";
import { requestSync } from "@/sync/useSync";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { MenuSheet } from "@/ui/MenuSheet";

import { CollectionTile } from "./CollectionTile";

const NEW_TILE_MIN_HEIGHT = 140;

/** Saved's Collections section: a tile per collection, then a "New collection" tile; long-press opens Rename/Delete. */
export function CollectionsSection() {
  const theme = useTheme();
  const router = useRouter();
  const collections = useCollectionsData();
  const [menuFor, setMenuFor] = useState<CollectionWithItems | null>(null);

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
            <CollectionTile
              collection={collection}
              onPress={() => {
                haptic("light");
                router.push({ pathname: "/collection/[id]", params: { id: collection.id } });
              }}
              onLongPress={() => {
                haptic("selection");
                setMenuFor(collection);
              }}
            />
          </View>
        ))}

        <Pressable
          testID="collection-new-tile"
          onPress={startNewCollection}
          style={{
            width: "48.5%",
            minHeight: NEW_TILE_MIN_HEIGHT,
            borderWidth: 1.5,
            borderColor: theme.colors.line,
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

      <MenuSheet
        visible={menuFor !== null}
        onClose={() => setMenuFor(null)}
        items={
          menuFor === null
            ? []
            : [
                {
                  label: "Rename",
                  testID: "collection-menu-rename",
                  onPress: () =>
                    promptCollectionName({
                      title: "Rename collection",
                      submitLabel: "Save",
                      initialName: menuFor.name,
                      onSubmit: (name) => {
                        renameCollection(db, menuFor.id, name);
                        requestSync();
                      },
                    }),
                },
                {
                  label: "Delete collection",
                  testID: "collection-menu-delete",
                  destructive: true,
                  startsGroup: true,
                  onPress: () =>
                    confirmDeleteCollection({
                      name: menuFor.name,
                      count: menuFor.items.length,
                      onConfirm: () => {
                        deleteCollection(db, menuFor.id);
                        haptic("success");
                        requestSync();
                      },
                    }),
                },
              ]
        }
      />
    </View>
  );
}
