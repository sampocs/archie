import { Button, ContextMenu, Host, Image, Label, Menu, RNHostView, Section, Text, type ButtonProps } from "@expo/ui/swift-ui";
import { accessibilityLabel } from "@expo/ui/swift-ui/modifiers";
import type { ReactElement } from "react";

import { useTheme } from "@/theme/useTheme";

import { menuSections, type MenuItem } from "./menuSections";

export type { MenuItem } from "./menuSections";

const MORE_GLYPH_SIZE = 22;

type MoreMenuProps = { testID: string; items: MenuItem[] };

/** The "…" button: tapping it pulls the menu down from the button itself. */
export function MoreMenu({ testID, items }: MoreMenuProps) {
  const theme = useTheme();

  return (
    <Host matchContents colorScheme={theme.scheme} testID={testID}>
      <Menu
        label={
          <Image
            systemName="ellipsis"
            size={MORE_GLYPH_SIZE}
            color={theme.colors.ink}
            modifiers={[accessibilityLabel("More")]}
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
