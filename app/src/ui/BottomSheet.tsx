import { ReactNode } from "react";
import { Modal, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme } from "@/theme/useTheme";

type BottomSheetProps = {
  visible: boolean;
  onClose: () => void;
  onDismiss?: () => void;
  children: ReactNode;
  testID?: string;
};

/** A modal sheet that slides up over a dimmed backdrop; tapping the backdrop closes it. */
export function BottomSheet({ visible, onClose, onDismiss, children, testID }: BottomSheetProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <Modal transparent visible={visible} animationType="slide" onRequestClose={onClose} onDismiss={onDismiss}>
      <View style={{ flex: 1, justifyContent: "flex-end" }}>
        <Pressable
          testID={testID ? `${testID}-backdrop` : undefined}
          onPress={onClose}
          style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 0, backgroundColor: "rgba(0,0,0,0.6)" }}
        />
        <View
          testID={testID}
          style={{
            backgroundColor: theme.colors.surface,
            borderTopLeftRadius: theme.radii.card,
            borderTopRightRadius: theme.radii.card,
            paddingHorizontal: theme.spacing.gutterCards,
            paddingTop: theme.spacing.md,
            paddingBottom: insets.bottom + theme.spacing.lg,
            gap: theme.spacing.md,
          }}
        >
          <View
            style={{
              alignSelf: "center",
              width: 36,
              height: 5,
              borderRadius: 3,
              backgroundColor: theme.colors.line,
            }}
          />
          {children}
        </View>
      </View>
    </Modal>
  );
}
