# Native menus

The app's action menus are all `MenuSheet`, a bottom sheet that slides up far from what was pressed. Replace them
with iOS's own menus, everywhere. The approved mock is at https://claude.ai/artifact/6TbTotvv44m3KLi1xr8695.

## Behavior

- **"…" buttons** open a pull-down menu anchored to the button (iOS `Menu`). The page stays sharp, with no dimming.
- **Long-press** on a row or card lifts it, blurs the rest of the screen, and shows the menu beside it (iOS context
  menu). A plain tap still does what it did before (opening the post, the chat, or the collection).
- **Fixed short lists become submenus that open in place:** a post's *Move to* (other collections, then
  *New collection…*, which prompts for a name and moves the post into it) and a take's *Change kind*.
- **Pickers keep their sheets:** *Remind me later…* (snooze), *Change topic*, *Wrong episode?* and a topic's
  *Merge into…* still open the sheet they open today, once the menu has closed.
- Destructive items show in red, last, in their own group. Confirmations that exist today stay as they are.
- Groups (`startsGroup`) become menu sections. Items keep their labels; each gets an SF Symbol where an obvious one
  exists.

Every `MenuSheet` call site moves: the collection page "…" and post long-press (`collection/[id]`, `PostMenus`),
Saved tiles (`CollectionsSection`), the item "…" (`ItemMenu`), chat "…" (`ask/[id]`), Ask list long-press
(`(tabs)/ask`), card "…" (`card/[id]`), take menus (`TakeMenus`) and topic menu (`TopicMenu`). `MenuSheet` is then
deleted.

## Approach

Use `@expo/ui` (SDK 58's first-party SwiftUI components, already in Expo's bundled module list): `Menu` for "…"
buttons and `ContextMenu` with an `RNHostView` trigger for long-press. It needs a native rebuild of the simulator dev
client and the phone build; no server change.

A shared module, `app/src/ui/NativeMenu.tsx`, keeps call sites free of SwiftUI:

- `MenuItem` keeps its shape (`label`, `onPress`, `destructive`, `testID`, `startsGroup`, `subtitle`) and gains
  `icon?: string` (SF Symbol) and `submenu?: MenuItem[]`.
- `<MoreMenu testID items />` renders the "…" glyph as the trigger.
- `<LongPressMenu items>{children}</LongPressMenu>` wraps any RN view; with no items it renders the children alone.

**Spike first.** The risk is an RN view hosted inside SwiftUI's context menu: tap pass-through, layout (width from the
parent, height from the content) inside a `ScrollView`, and scrolling that starts on a wrapped card. If any of these
fails on the simulator, swap the module's internals to `react-native-ios-context-menu` (a UIKit
`UIContextMenuInteraction` wrapping the RN view directly) without changing its props.

## Testing

- Maestro can't reliably see `testID`s on native menu items, so flows that open a menu tap items by their label text
  (`collections`, `chat_cards`, `edit`, `newsletter_2_go_deeper`, `finish_item`, `takes`, `topics`). Each flow still
  opens the menu by its trigger's `testID` or a `longPressOn`.
- Unit tests: only the pure item → section grouping in `NativeMenu` (groups split on `startsGroup`, destructive last).
- Manual check on the simulator for each call site: the menu opens where it should, and the action runs.

## Build plan

### Chunk 1: NativeMenu and the spike (most capable tier)
- `npx expo install @expo/ui`, rebuild the simulator dev client (`npx expo run:ios`).
- `app/src/ui/NativeMenu.tsx`: `MenuItem`, `MoreMenu`, `LongPressMenu`, and the grouping helper, with its test.
- Move the collection page (its "…" and the post long-press via `PostMenus`, including the Move to submenu with
  New collection…) and Saved tiles to it, as the spike's proof. Update `maestro/collections.yaml`.
- Verify on the simulator: tap still opens a post, long-press lifts it, scrolling works when it starts on a card,
  "…" pulls down from the button. Fall back to `react-native-ios-context-menu` if not, as described above.
- Depends on: none.

### Chunk 2: every other call site
- `ItemMenu`, `ask/[id]`, `(tabs)/ask`, `card/[id]`, `TakeMenus` (Change kind as a submenu), `TopicMenu`. Picker items
  open their existing sheets after the menu closes.
- Delete `MenuSheet` once nothing imports it.
- Update the remaining Maestro flows listed under Testing and run them.
- Depends on: chunk 1.
