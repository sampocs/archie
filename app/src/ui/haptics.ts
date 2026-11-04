import * as Haptics from "expo-haptics";

export type HapticEvent = "selection" | "light" | "success";

/** Fire-and-forget feedback; never awaited so a UI handler isn't delayed by it. */
export function haptic(event: HapticEvent): void {
  if (event === "selection") void Haptics.selectionAsync();
  else if (event === "light") void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
  else void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
}
