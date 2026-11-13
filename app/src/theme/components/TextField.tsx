import { StyleSheet, TextInput, TextInputProps } from "react-native";

import { useAllowFontScaling } from "../fontScaling";
import { textStyles } from "../type";
import { useTheme } from "../useTheme";

export function TextField({ style, ...rest }: TextInputProps) {
  const theme = useTheme();
  const allowFontScaling = useAllowFontScaling();

  return (
    <TextInput
      allowFontScaling={allowFontScaling}
      placeholderTextColor={theme.colors.ink3}
      {...rest}
      style={[
        styles.field,
        rest.multiline ? styles.multiline : null,
        textStyles.body,
        { backgroundColor: theme.colors.press, color: theme.colors.ink, borderRadius: theme.radii.button },
        style,
      ]}
    />
  );
}

const styles = StyleSheet.create({
  field: { minHeight: 50, paddingHorizontal: 16 },
  // A multiline input pins its text to the top, so pad it to sit centered while it's one line, as a single-line field does.
  multiline: { paddingTop: 14, paddingBottom: 14 },
});
