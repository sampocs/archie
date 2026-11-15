import { Ionicons } from "@expo/vector-icons";
import { useRef, useState } from "react";
import { Pressable, View, type TextInputInstance } from "react-native";

import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";

type ComposerProps = {
  placeholder: string;
  disabled: boolean;
  disabledLabel?: string;
  /** Keeps the field editable but blocks sending (an answer is still streaming). */
  sendDisabled?: boolean;
  onSend: (text: string, web: boolean) => void;
  initialWeb?: boolean;
  // "bar": a one-line field beside its buttons, under a chat. "hero": the Ask tab's large box, buttons inside it.
  variant?: "bar" | "hero";
};

const ICON_SIZE = 30;
// About four lines of body text before the hero box grows, and where it stops growing and scrolls (short enough to leave the heading and buttons above the keyboard on a 4.7" iPhone).
const HERO_MIN_HEIGHT = 96;
const HERO_MAX_HEIGHT = 160;

/** The question box: a field, the globe that forces a web search, and send. Offline it says why it is gone. */
export function Composer({
  placeholder,
  disabled,
  disabledLabel,
  sendDisabled = false,
  onSend,
  initialWeb = false,
  variant = "bar",
}: ComposerProps) {
  const theme = useTheme();
  const input = useRef<TextInputInstance>(null);
  const [text, setText] = useState("");
  const [web, setWeb] = useState(initialWeb);
  const empty = text.trim() === "";

  if (disabled) {
    return (
      <Text testID="ask-offline" tone="ink3">
        {disabledLabel}
      </Text>
    );
  }

  function send(): void {
    if (empty || sendDisabled) return;
    onSend(text.trim(), web);
    setText("");
    setWeb(false);
  }

  const buttons = (
    <>
      <Pressable
        testID="ask-web-toggle"
        accessibilityLabel="Search the web"
        accessibilityRole="button"
        accessibilityState={{ selected: web }}
        onPress={() => setWeb((current) => !current)}
        hitSlop={8}
        style={variant === "bar" ? { paddingBottom: 10 } : null}
      >
        <Ionicons
          name={web ? "globe" : "globe-outline"}
          size={ICON_SIZE}
          color={web ? theme.colors.chrome : theme.colors.ink3}
        />
      </Pressable>
      <Pressable
        testID="ask-send"
        onPress={send}
        disabled={empty || sendDisabled}
        hitSlop={8}
        style={variant === "bar" ? { paddingBottom: 10 } : null}
      >
        <Ionicons name="arrow-up-circle" size={ICON_SIZE} color={empty || sendDisabled ? theme.colors.ink3 : theme.colors.chrome} />
      </Pressable>
    </>
  );

  if (variant === "hero") {
    return (
      // A tap anywhere in the box (around the text, beside the buttons) types into it rather than closing the keyboard.
      <Pressable
        accessible={false}
        onPress={() => input.current?.focus()}
        style={{ backgroundColor: theme.colors.press, borderRadius: theme.radii.card, paddingBottom: theme.spacing.md }}
      >
        <TextField
          ref={input}
          testID="ask-composer-input"
          value={text}
          onChangeText={setText}
          placeholder={placeholder}
          multiline
          style={{ minHeight: HERO_MIN_HEIGHT, maxHeight: HERO_MAX_HEIGHT, backgroundColor: "transparent" }}
        />
        <View
          style={{
            flexDirection: "row",
            justifyContent: "flex-end",
            gap: theme.spacing.md,
            paddingHorizontal: theme.spacing.md,
          }}
        >
          {buttons}
        </View>
      </Pressable>
    );
  }

  return (
    <View style={{ flexDirection: "row", alignItems: "flex-end", gap: theme.spacing.sm }}>
      <TextField
        testID="ask-composer-input"
        value={text}
        onChangeText={setText}
        placeholder={placeholder}
        multiline
        style={{ flex: 1, maxHeight: 140 }}
      />
      {buttons}
    </View>
  );
}
