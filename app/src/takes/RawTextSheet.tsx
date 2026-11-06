import { ScrollView } from "react-native";

import { Text } from "@/theme/components/Text";
import { BottomSheet } from "@/ui/BottomSheet";

type RawTextSheetProps = { visible: boolean; rawBody: string; onClose: () => void };

/** What the owner actually said, before Clean it up, read-only. */
export function RawTextSheet({ visible, rawBody, onClose }: RawTextSheetProps) {
  return (
    <BottomSheet visible={visible} onClose={onClose} testID="take-raw-sheet">
      <Text variant="headline">What you said</Text>
      <ScrollView style={{ maxHeight: 360 }}>
        <Text testID="take-raw-text" selectable>
          {rawBody}
        </Text>
      </ScrollView>
    </BottomSheet>
  );
}
