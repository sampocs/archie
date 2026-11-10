import { Pressable, ScrollView, useWindowDimensions, View } from "react-native";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { BottomSheet } from "@/ui/BottomSheet";
import { Markdown } from "@/ui/Markdown";

type CheatSheetSheetProps = { title: string; markdown: string; visible: boolean; onClose: () => void };

/** A proposed cheat sheet in full, rendered as its Library item will show it; Done or the backdrop closes it. */
export function CheatSheetSheet({ title, markdown, visible, onClose }: CheatSheetSheetProps) {
  const theme = useTheme();
  const { height } = useWindowDimensions();

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="cheat-sheet-sheet">
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
        <Text variant="kicker" tone="ink3">
          Cheat sheet · preview
        </Text>
        <Pressable testID="cheat-sheet-done" onPress={onClose} hitSlop={12}>
          <Text tone="ink2">Done</Text>
        </Pressable>
      </View>
      <ScrollView style={{ maxHeight: height * 0.75 }} contentContainerStyle={{ gap: theme.spacing.md }}>
        <Text variant="articleTitle">{title}</Text>
        <Markdown text={markdown} />
      </ScrollView>
    </BottomSheet>
  );
}
