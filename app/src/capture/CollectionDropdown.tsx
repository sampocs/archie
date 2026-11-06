import { ActionSheetIOS, Pressable } from "react-native";

import { promptCollectionName } from "@/collections/prompts";
import type { SharedCollection } from "@/collections/sharedCollectionsFormat";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

import { collectionPickLabel } from "./collectionChoice";
import type { CollectionPick } from "./types";

type CollectionDropdownProps = {
  collections: SharedCollection[];
  pick: CollectionPick;
  onPick: (pick: CollectionPick) => void;
};

/** App only: a native action sheet and system prompt, which the share extension cannot present. */
export function CollectionDropdown({ collections, pick, onPick }: CollectionDropdownProps) {
  const theme = useTheme();

  function open(): void {
    const names = collections.map((collection) => collection.name);
    ActionSheetIOS.showActionSheetWithOptions(
      { options: [...names, "＋ New collection…", "Cancel"], cancelButtonIndex: names.length + 1 },
      (index) => {
        if (index === names.length) {
          promptCollectionName({
            title: "New collection",
            submitLabel: "Create",
            onSubmit: (name) => {
              haptic("selection");
              onPick({ kind: "new", name });
            },
          });
          return;
        }
        if (index > names.length) return;

        haptic("selection");
        onPick({ kind: "existing", id: collections[index].id });
      },
    );
  }

  return (
    <Pressable
      testID="collection-dropdown"
      onPress={open}
      style={{
        height: 40,
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: theme.spacing.md,
        backgroundColor: theme.colors.press,
        borderRadius: theme.radii.chip,
      }}
    >
      <Text numberOfLines={1} style={{ flex: 1 }}>
        {collectionPickLabel(pick, collections)}
      </Text>
      <Text tone="ink3">▾</Text>
    </Pressable>
  );
}
