import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";

import { deleteCollection, renameCollection } from "@/db/actions";
import { db } from "@/db/client";
import { savedCountLabel, type CollectionItemRow } from "@/collections/collections";
import { PostCard } from "@/collections/PostCard";
import { PostMenus } from "@/collections/PostMenus";
import { confirmDeleteCollection, promptCollectionName } from "@/collections/prompts";
import { useCollectionsState } from "@/collections/useCollectionsData";
import { requestSync } from "@/sync/useSync";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";
import { MenuSheet, type MenuItem } from "@/ui/MenuSheet";

export default function CollectionScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const theme = useTheme();
  const { collections, loaded } = useCollectionsState();
  const [menuOpen, setMenuOpen] = useState(false);
  const [postInMenu, setPostInMenu] = useState<CollectionItemRow | null>(null);

  const collection = collections.find((candidate) => candidate.id === id);

  // Deleted here or on another device: nothing left to show.
  useEffect(() => {
    if (loaded && !collection) router.back();
  }, [loaded, collection, router]);

  if (!loaded || !collection) return null;

  const menuItems: MenuItem[] = [
    {
      testID: "collection-menu-rename",
      label: "Rename",
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
      testID: "collection-menu-delete",
      label: "Delete collection",
      destructive: true,
      startsGroup: true,
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

  return (
    <Screen
      title=""
      onBack={router.back}
      headerRight={
        <Pressable testID="collection-more" accessibilityLabel="More" hitSlop={12} onPress={() => setMenuOpen(true)}>
          <Ionicons name="ellipsis-horizontal" size={24} color={theme.colors.ink} />
        </Pressable>
      }
    >
      <View testID="collection-page" style={{ gap: theme.spacing.md }}>
        <View style={{ gap: 4 }}>
          <Text variant="kicker" tone="ink3" testID="collection-kicker">
            {`Collection · ${savedCountLabel(collection.items.length)}`}
          </Text>
          <Text variant="largeTitle">{collection.name}</Text>
        </View>
        <View style={{ gap: 14 }}>
          {collection.items.length === 0 ? (
            <Text tone="ink2" testID="collection-empty">
              Nothing saved here yet.
            </Text>
          ) : (
            collection.items.map((item) => (
              <PostCard key={item.id} item={item} onLongPress={() => setPostInMenu(item)} />
            ))
          )}
        </View>
      </View>
      <MenuSheet visible={menuOpen} onClose={() => setMenuOpen(false)} items={menuItems} />
      <PostMenus item={postInMenu} collections={collections} onClose={() => setPostInMenu(null)} />
    </Screen>
  );
}
