import { Children, createContext, ReactNode } from "react";
import { StyleSheet, View } from "react-native";

import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type GroupedListProps = { title?: string; right?: ReactNode; children: ReactNode; testID?: string };

// `roundTop` / `roundBottom`: the row sits at the card's top or bottom, so what it slides out is clipped to the card's
// rounded corners there.
export type RowBleed = { left: number; right: number; roundTop: boolean; roundBottom: boolean };

/**
 * How far a row's own background may reach past its padding to the card's edges. A swipe row bleeds by this much so
 * its actions run to the card's rounded edge instead of stopping at the padding.
 */
export const NO_BLEED: RowBleed = { left: 0, right: 0, roundTop: false, roundBottom: false };
export const RowBleedContext = createContext<RowBleed>(NO_BLEED);

/** A section label row above a card of children separated by hairlines. */
export function GroupedList({ title, right, children, testID }: GroupedListProps) {
  const theme = useTheme();
  const items = Children.toArray(children);
  const inset = theme.spacing.lg;

  return (
    <View testID={testID} style={{ gap: theme.spacing.sm }}>
      {title || right ? (
        <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center" }}>
          <Text variant="monoLabel" tone="ink3">
            {title}
          </Text>
          {right}
        </View>
      ) : null}
      <Card style={{ padding: 0 }}>
        {items.map((child, index) => (
          <View key={index} style={{ paddingHorizontal: inset }}>
            {index > 0 ? (
              <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: theme.colors.line }} />
            ) : null}
            <RowBleedContext.Provider
              value={{ left: inset, right: inset, roundTop: index === 0, roundBottom: index === items.length - 1 }}
            >
              {child}
            </RowBleedContext.Provider>
          </View>
        ))}
      </Card>
    </View>
  );
}
