import { requireOptionalNativeModule } from "expo-modules-core";

import type { WidgetSnapshot } from "./widgetSnapshot";

type ArchieWidgetModule = { setSnapshot(json: string): Promise<void>; clear(): Promise<void> };

// Null in jest, Expo Go and any build without the native module, which makes both calls no-ops.
const widgetModule = requireOptionalNativeModule<ArchieWidgetModule>("ArchieWidget");

/** Hands the snapshot to the widget. Best effort: a stale widget is harmless, so failures are ignored. */
export function publishWidgetSnapshot(snapshot: WidgetSnapshot): void {
  widgetModule?.setSnapshot(JSON.stringify(snapshot)).catch(() => undefined);
}

/** Empties the widget, so a signed-out phone never shows the last user's progress. */
export function clearWidget(): void {
  widgetModule?.clear().catch(() => undefined);
}
