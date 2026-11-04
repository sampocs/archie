import { Children, ReactNode } from "react";
import { StyleSheet, View } from "react-native";

import { Card } from "@/theme/components/Card";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

type GroupedListProps = { title?: string; right?: ReactNode; children: ReactNode; testID?: string };

/** A section label row above a card of children separated by hairlines. */
export function GroupedList({ title, right, children, testID }: GroupedListProps) {
  const theme = useTheme();
  const items = Children.toArray(children);

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
      <Card style={{ paddingVertical: 0 }}>
        {items.map((child, index) => (
          <View
            key={index}
            style={index > 0 ? { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: theme.colors.line } : null}
          >
            {child}
          </View>
        ))}
      </Card>
    </View>
  );
}
