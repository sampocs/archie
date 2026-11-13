# Lock-screen widget: today's cards, notes and brief

## What

One iOS lock-screen widget (`accessoryRectangular`, the wide slot) showing three progress rings for Today's
tasks, in this order:

| Ring | Task on Today | SF Symbol |
| --- | --- | --- |
| Cards | the review set (`todayTasks().review`) | `rectangle.stack` |
| Notes | the note refresher (`todayTasks().notes`) | `book.closed` |
| Brief | the news brief (`todayTasks().brief`) | `cup.and.saucer` |

Mock: https://claude.ai/artifact/XkxofDF7s1CUZYaA3N21MZ (version A, set by hand to the three symbols above).

- Each ring fills as its task progresses and its symbol turns into a checkmark (`checkmark`) when the task is done.
- A task with nothing today (its `todayTasks` entry is `null`) shows its symbol dimmed (about 40% opacity) on an
  empty track.
- The whole widget is one tap target and just opens Archie (no `widgetURL`, no deep links).
- The weekly news quiz is not shown.
- Lock-screen widgets are tinted by iOS, so everything draws in the primary foreground style; the track is the same
  style at reduced opacity. No home-screen sizes (YAGNI).

## How it gets its data

A widget can't run JS or read the app's SQLite database, so the app publishes a small JSON snapshot for it.

**Where it lives: the shared Keychain group, not an App Group.** The app and the share extension already share
`$(AppIdentifierPrefix)com.sampocs.archie.shared` (see `app/plugins/withSharedKeychain.js`, which notes that the Apple
portal has no App Group set up and automatic signing fails with one). The widget extension gets the same
`keychain-access-groups` entitlement and reads one generic-password item:

- service `com.sampocs.archie.widget`, account `today`, access group `3W3H65F89G.com.sampocs.archie.shared`
- accessible `kSecAttrAccessibleAfterFirstUnlock`, so the lock-screen widget can read it while the phone is locked
- value: UTF-8 JSON, the snapshot below

**The snapshot (version 1):**

```json
{
  "version": 1,
  "days": [
    { "day": "2026-11-13", "rings": { "cards": { "progress": 0.67, "done": false }, "notes": { "progress": 1, "done": true }, "brief": null } },
    { "day": "2026-11-14", "rings": { "cards": { "progress": 0, "done": false }, "notes": { "progress": 0, "done": false }, "brief": { "progress": 0, "done": false } } }
  ]
}
```

- `day` is the phone's local date (`YYYY-MM-DD`). `days[0]` is today and `days[1]` tomorrow.
- A ring is `null` (nothing that day) or `{ progress: 0..1, done }`.
- **Today:**
  - Cards: pending → 0; under way → `reviewed / total`; done → 1 and done.
  - Notes: pending → 0; under way → `(position - 1) / DAILY_NOTES`; done → 1 and done.
  - Brief: pending → 0; done → 1 and done.
- **Tomorrow:** each ring is at 0 if tomorrow already holds that task, else `null`. The counts are the ones
  `backTomorrow` already computes: cards > 0, notes > 0, and a brief when today's brief is done. Extract them into
  a `tomorrowCounts(inputs)` that `backTomorrow` reuses, so the two can't drift.

**Publishing (app side).**
- A local Expo module, `archie-widget` (`app/modules/archie-widget`, Swift), exposes `setSnapshot(json: string)` and
  `clear()`. Both write or delete the Keychain item, then call `WidgetCenter.shared.reloadAllTimelines()`.
- The JS wrapper loads it with `requireOptionalNativeModule`, so jest and any build without it are no-ops.
- The Today screen builds the snapshot from the `TodayTaskView` it already has, then publishes it in an effect
  whenever the serialized JSON changes. Today's live queries keep it current as cards are graded, notes refreshed
  and the brief marked Done, including from screens stacked on top of Today.
- Sign-out calls `clear()`, so a signed-out phone shows empty rings rather than the last user's progress.

**Rendering (widget side).** The widget is a WidgetKit extension in Swift/SwiftUI, added to the native project by
`@bacons/apple-targets` from `app/targets/widget/`.
- **Timeline:** one entry per known day. `days[0]` is shown now and `days[1]` from the next local midnight, then a
  final entry the midnight after that with an unknown day.
- **Refresh policy:** `.never`. The app's reloads drive updates.
- **No snapshot, or a day not in it:** plain empty rings with full-opacity symbols. That case means "unknown",
  not "nothing today".
- **Unknown `version`:** treated as no snapshot.
- Uses `containerBackground(for: .widget)` on iOS 17+ for proper lock-screen rendering.
- The deployment target matches the app's 16.4. `accessoryRectangular` needs iOS 16.

## Error handling

- **Keychain write failures** are swallowed by the module (a stale widget is harmless); the module logs them.
- **Widget read or decode failures** fall back to the "unknown" rendering.
- **Missing native module** (jest, Expo Go): the wrapper does nothing.

## Testing

- Unit tests (jest) for the pure snapshot builder, `widgetSnapshot(view, inputs) → Snapshot`:
  - pending, under way and done for each ring;
  - `null` tasks;
  - tomorrow's rings (cards only, notes only, brief only after today's brief is done, none);
  - day strings across a month boundary.
- `backTomorrow` tests stay green after the `tomorrowCounts` extraction.
- Native: `npx expo prebuild --clean` then a simulator build (`npx expo run:ios`) must compile the app, the share
  extension and the widget. The real proof is on the phone: install with `scripts/install_ios.sh`, then the owner adds
  the widget to the lock screen.

## Build plan

### Chunk 1 — snapshot and publishing (JS)
Depends on: none (codes against the module's JS interface below).
- `app/src/today/todayTasks.ts`: extract `tomorrowCounts(inputs): { cards: number; notes: number; brief: boolean }`
  and have `backTomorrow` use it.
- New `app/src/widget/widgetSnapshot.ts`: types `WidgetRing`, `WidgetDay` and `WidgetSnapshot` (version 1), plus
  `widgetSnapshot(view, inputs)`. Tests in `widgetSnapshot.test.ts`.
- New `app/src/widget/publish.ts`: `publishWidgetSnapshot(snapshot)` and `clearWidget()` over the optional native
  module `ArchieWidget` (`setSnapshot(json: string): Promise<void>`, `clear(): Promise<void>`). Both are no-ops when
  the module is missing.
- `app/src/app/(tabs)/today.tsx`: build the snapshot from `view` plus the inputs it already has, and publish it in an
  effect keyed on its JSON.
- Sign-out path (find where the session is cleared): call `clearWidget()`.

### Chunk 2 — native module and widget extension
Depends on: none (the snapshot format above is the contract).
- `app/modules/archie-widget/`: a local Expo module (`expo-module.config.json`, `ios/ArchieWidgetModule.swift`, podspec,
  `index.ts`). The module name `ArchieWidget` exposes `setSnapshot` and `clear`, which use the Keychain item and reload
  timelines as specified.
- Add `@bacons/apple-targets` (pinned) and list it in `app.config.ts` plugins.
- `app/targets/widget/`:
  - `expo-target.config.js`: type `widget`; bundle id `com.sampocs.archie.widget`; `keychain-access-groups`
    entitlement `$(AppIdentifierPrefix)com.sampocs.archie.shared`; deployment target 16.4.
  - Swift: the bundle, the timeline provider (Keychain read and decode, entries per day), and the rings view with the
    three SF Symbols.
- Make sure `withSharedKeychain.js` (which looks up the share extension directory by name) still works with a second
  extension target. Neither plugin may add an App Group to any target.
- Verify: `npx expo prebuild --platform ios --clean`, then a simulator build that compiles all three targets.
