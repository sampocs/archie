import { Ionicons } from "@expo/vector-icons";
import { useState } from "react";
import { Pressable, View } from "react-native";

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
};

const ICON_SIZE = 30;

/** The question box: a field, the globe that forces a web search, and send. Offline it says why it is gone. */
export function Composer({ placeholder, disabled, disabledLabel, sendDisabled = false, onSend, initialWeb = false }: ComposerProps) {
  const theme = useTheme();
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
      <Pressable
        testID="ask-web-toggle"
        accessibilityLabel="Search the web"
        accessibilityRole="button"
        accessibilityState={{ selected: web }}
        onPress={() => setWeb((current) => !current)}
        hitSlop={8}
        style={{ paddingBottom: 10 }}
      >
        <Ionicons
          name={web ? "globe" : "globe-outline"}
          size={ICON_SIZE}
          color={web ? theme.colors.chrome : theme.colors.ink3}
        />
      </Pressable>
      <Pressable testID="ask-send" onPress={send} disabled={empty || sendDisabled} hitSlop={8} style={{ paddingBottom: 10 }}>
        <Ionicons name="arrow-up-circle" size={ICON_SIZE} color={empty || sendDisabled ? theme.colors.ink3 : theme.colors.chrome} />
      </Pressable>
    </View>
  );
}
