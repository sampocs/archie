/**
 * One action in a native menu. `startsGroup` opens a new section, `icon` is an SF Symbol name, and an item with a
 * `submenu` opens that list in place instead of running `onPress`.
 */
export type MenuItem = {
  label: string;
  destructive?: boolean;
  testID: string;
  subtitle?: string;
  startsGroup?: boolean;
  icon?: string;
} & ({ onPress: () => void; submenu?: undefined } | { submenu: MenuItem[]; onPress?: undefined });

/** Splits items into menu sections at each `startsGroup`; destructive items always end up together, in a last section. */
export function menuSections(items: MenuItem[]): MenuItem[][] {
  const sections: MenuItem[][] = [];
  for (const item of items.filter((candidate) => !candidate.destructive)) {
    const current = sections[sections.length - 1];
    if (current === undefined || item.startsGroup) sections.push([item]);
    else current.push(item);
  }

  const destructive = items.filter((item) => item.destructive);
  return destructive.length > 0 ? [...sections, destructive] : sections;
}
