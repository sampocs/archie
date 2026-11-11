import { Pressable } from "react-native-gesture-handler";

/**
 * A whole-card or whole-row tap target inside a scrolling screen. It is react-native-gesture-handler's Pressable, so a
 * scroll that starts on it cancels the tap like a native iOS button; React Native's core Pressable isn't part of the
 * native gesture arbitration and would open the card at the end of a scroll.
 */
export const Tappable = Pressable;
