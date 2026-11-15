import { menuSections, type MenuItem } from "./menuSections";

const item = (testID: string, overrides: Partial<MenuItem> = {}): MenuItem => ({
  testID,
  label: testID,
  onPress: () => {},
  ...overrides,
});

const ids = (sections: MenuItem[][]) => sections.map((section) => section.map((entry) => entry.testID));

describe("menuSections", () => {
  it("starts a new section at each startsGroup", () => {
    const sections = menuSections([item("a"), item("b"), item("c", { startsGroup: true }), item("d")]);
    expect(ids(sections)).toEqual([["a", "b"], ["c", "d"]]);
  });

  it("moves destructive items into their own last section, wherever they were", () => {
    const sections = menuSections([
      item("delete", { destructive: true }),
      item("rename"),
      item("archive", { destructive: true, startsGroup: true }),
      item("share", { startsGroup: true }),
    ]);
    expect(ids(sections)).toEqual([["rename"], ["share"], ["delete", "archive"]]);
  });

  it("returns no sections for no items", () => {
    expect(menuSections([])).toEqual([]);
  });
});
