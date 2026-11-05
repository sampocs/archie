import { useRef } from "react";
import { Pressable, StyleSheet } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

import { BottomSheet } from "./BottomSheet";

// `startsGroup` draws a divider above the item, so related actions read as one group.
export type MenuItem = {
  label: string;
  onPress: () => void;
  destructive?: boolean;
  testID: string;
  subtitle?: string;
  startsGroup?: boolean;
};
type MenuSheetProps = { visible: boolean; onClose: () => void; items: MenuItem[] };

/** A list of full-width actions; choosing one closes the sheet, and runs it once the sheet has fully dismissed. */
export function MenuSheet({ visible, onClose, items }: MenuSheetProps) {
  const theme = useTheme();
  // iOS drops a modal presented while another is still dismissing, so a chosen action waits for onDismiss.
  const chosen = useRef<MenuItem | null>(null);

  return (
    <BottomSheet
      visible={visible}
      onClose={onClose}
      onDismiss={() => {
        const item = chosen.current;
        chosen.current = null;
        item?.onPress();
      }}
      testID="menu-sheet"
    >
      {items.map((item) => (
        <Pressable
          key={item.testID}
          testID={item.testID}
          onPress={() => {
            chosen.current = item;
            onClose();
          }}
          style={[
            { paddingVertical: theme.spacing.md, gap: 2 },
            item.startsGroup ? { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.line } : null,
          ]}
        >
          <Text variant="body" style={item.destructive ? { color: theme.signals.missed } : undefined}>
            {item.label}
          </Text>
          {item.subtitle ? (
            <Text variant="secondary" tone="ink3">
              {item.subtitle}
            </Text>
          ) : null}
        </Pressable>
      ))}
    </BottomSheet>
  );
}
