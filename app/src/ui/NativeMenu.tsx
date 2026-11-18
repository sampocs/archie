import { Button, ContextMenu, Host, Image, Label, Menu, RNHostView, Section, Text, type ButtonProps } from "@expo/ui/swift-ui";
import { accessibilityLabel, contentShape, frame, shapes } from "@expo/ui/swift-ui/modifiers";
import type { ReactElement } from "react";

import { useTheme } from "@/theme/useTheme";

import { menuSections, type MenuItem } from "./menuSections";

export type { MenuItem } from "./menuSections";

const MORE_GLYPH_SIZE = 22;
// The glyph is only a few points tall, so the button gets Apple's 44pt touch height and some width to its left. Negative
// margins give the extra back to the layout, so headers keep the height and spacing they had with the bare glyph.
const MORE_HIT = { width: 40, height: 44 };
const MORE_LAYOUT = { width: 26, height: 22 };
const MORE_OVERHANG = {
  marginVertical: -(MORE_HIT.height - MORE_LAYOUT.height) / 2,
  marginLeft: -(MORE_HIT.width - MORE_LAYOUT.width),
};

type MoreMenuProps = { testID: string; items: MenuItem[]; accessibilityLabel?: string };

/** The "…" button: tapping it pulls the menu down from the button itself. */
export function MoreMenu({ testID, items, accessibilityLabel: label = "More" }: MoreMenuProps) {
  const theme = useTheme();

  return (
    <Host matchContents colorScheme={theme.scheme} testID={testID} style={MORE_OVERHANG}>
      <Menu
        label={
          <Image
            systemName="ellipsis"
            size={MORE_GLYPH_SIZE}
            color={theme.colors.ink}
            modifiers={[
              frame({ ...MORE_HIT, alignment: "trailing" }),
              contentShape(shapes.rectangle()),
              accessibilityLabel(label),
            ]}
          />
        }
      >
        <MenuEntries items={items} />
      </Menu>
    </Host>
  );
}

type LongPressMenuProps = { items: MenuItem[]; children: ReactElement; fitContent?: boolean };

/**
 * Long-pressing the children lifts them and shows the menu beside them; a plain tap still reaches them. The children
 * take their width from the parent and their height from their own content; `fitContent` takes the width from the
 * content too, for a chip that sits in a wrapping row.
 */
export function LongPressMenu({ items, children, fitContent = false }: LongPressMenuProps) {
  const theme = useTheme();
  if (items.length === 0) return children;

  const matchContents = fitContent ? true : { vertical: true };
  return (
    <Host matchContents={matchContents} colorScheme={theme.scheme}>
      <ContextMenu>
        <ContextMenu.Items>
          <MenuEntries items={items} />
        </ContextMenu.Items>
        <ContextMenu.Trigger>
          <RNHostView matchContents={matchContents}>{children}</RNHostView>
        </ContextMenu.Trigger>
      </ContextMenu>
    </Host>
  );
}

// The system draws a separator between sections, which is how groups and the destructive tail read apart.
function MenuEntries({ items }: { items: MenuItem[] }) {
  return menuSections(items).map((section) => (
    <Section key={section[0].testID}>
      {section.map((item) => (
        <MenuEntry key={item.testID} item={item} />
      ))}
    </Section>
  ));
}

// Maestro can't see testIDs on native menu items (flows tap them by label); they're passed for keys and other tooling.
function MenuEntry({ item }: { item: MenuItem }) {
  const systemImage = item.icon as ButtonProps["systemImage"];
  if (item.submenu) {
    return (
      <Menu label={item.label} systemImage={systemImage} testID={item.testID}>
        <MenuEntries items={item.submenu} />
      </Menu>
    );
  }

  const onPress = item.onPress;
  const role = item.destructive ? "destructive" : "default";
  if (!item.subtitle) {
    return <Button testID={item.testID} label={item.label} systemImage={systemImage} role={role} onPress={onPress} />;
  }

  // A menu button whose label holds two texts shows the second as a smaller line under the first.
  return (
    <Button testID={item.testID} role={role} onPress={onPress}>
      {systemImage ? <Label title={item.label} systemImage={systemImage} /> : <Text>{item.label}</Text>}
      <Text>{item.subtitle}</Text>
    </Button>
  );
}
