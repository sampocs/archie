import { ReactNode, useContext } from "react";
import { Pressable, View } from "react-native";
import ReanimatedSwipeable, { type SwipeableMethods } from "react-native-gesture-handler/ReanimatedSwipeable";

import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { RowBleedContext } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";

export type SwipeTone = "neutral" | "chrome" | "gotIt" | "missed";

export type SwipeAction = { key: string; label: string; tone: SwipeTone; testID: string; onPress: () => void };

type SwipeRowProps = { actions: SwipeAction[]; children: ReactNode; testID?: string };

const ACTION_WIDTH = 72;

/** Swipe left to reveal up to three actions; the row closes after any of them. No actions, no swipe. */
export function SwipeRow({ actions, children, testID }: SwipeRowProps) {
  const theme = useTheme();
  const bleed = useContext(RowBleedContext);

  if (actions.length === 0) return <View testID={testID}>{children}</View>;

  const background: Record<SwipeTone, string> = {
    neutral: theme.colors.ink3,
    chrome: theme.colors.chrome,
    gotIt: theme.signals.gotIt,
    missed: theme.signals.missed,
  };

  function renderActions(methods: SwipeableMethods): ReactNode {
    return (
      <View style={{ flexDirection: "row" }}>
        {actions.map((action) => (
          <Pressable
            key={action.key}
            testID={action.testID}
            onPress={() => {
              methods.close();
              action.onPress();
            }}
            style={{
              width: ACTION_WIDTH,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: background[action.tone],
            }}
          >
            <Text variant="secondary" tone="onChrome">
              {action.label}
            </Text>
          </Pressable>
        ))}
      </View>
    );
  }

  return (
    <ReanimatedSwipeable
      testID={testID}
      friction={2}
      rightThreshold={ACTION_WIDTH / 2}
      overshootRight={false}
      onSwipeableWillOpen={() => haptic("light")}
      renderRightActions={(_progress, _translation, methods) => renderActions(methods)}
      // Reaching past the list's padding to the card's edges, so the row slides out and the actions end flush with
      // the card instead of leaving a strip of padding beside them.
      containerStyle={{ marginLeft: -bleed.left, marginRight: -bleed.right }}
      childrenContainerStyle={{
        backgroundColor: theme.colors.surface,
        paddingLeft: bleed.left,
        paddingRight: bleed.right,
      }}
    >
      {children}
    </ReanimatedSwipeable>
  );
}
