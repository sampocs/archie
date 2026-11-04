import { Pressable } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { BottomSheet } from "./BottomSheet";

type MenuItem = { label: string; onPress: () => void; destructive?: boolean; testID: string };
type MenuSheetProps = { visible: boolean; onClose: () => void; items: MenuItem[] };

/** A list of full-width actions; choosing one closes the sheet first, then runs it. */
export function MenuSheet({ visible, onClose, items }: MenuSheetProps) {
  const theme = useTheme();

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="menu-sheet">
      {items.map((item) => (
        <Pressable
          key={item.testID}
          testID={item.testID}
          onPress={() => {
            onClose();
            item.onPress();
          }}
          style={{ paddingVertical: theme.spacing.md }}
        >
          <Text variant="body" style={item.destructive ? { color: theme.signals.missed } : undefined}>
            {item.label}
          </Text>
        </Pressable>
      ))}
    </BottomSheet>
  );
}
