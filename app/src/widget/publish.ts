import { requireOptionalNativeModule } from "expo-modules-core";

type ArchieWidgetModule = { setSnapshot(json: string): Promise<void>; clear(): Promise<void> };

// Null in jest, Expo Go and any build without the native module, which makes both calls no-ops.
const widgetModule = requireOptionalNativeModule<ArchieWidgetModule>("ArchieWidget");

/** Hands the snapshot (a serialized `WidgetSnapshot`) to the widget. Best effort: a stale widget is harmless. */
export function publishWidgetSnapshot(snapshotJson: string): void {
  widgetModule?.setSnapshot(snapshotJson).catch(() => undefined);
}

/** Empties the widget, so a signed-out phone never shows the last user's progress. */
export function clearWidget(): void {
  widgetModule?.clear().catch(() => undefined);
}
