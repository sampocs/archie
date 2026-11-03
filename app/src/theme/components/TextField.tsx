import { StyleSheet, TextInput, TextInputProps } from "react-native";

import { textStyles } from "../type";
import { useTheme } from "../useTheme";

export function TextField({ style, ...rest }: TextInputProps) {
  const theme = useTheme();

  return (
    <TextInput
      placeholderTextColor={theme.colors.ink3}
      {...rest}
      style={[
        styles.field,
        textStyles.body,
        { backgroundColor: theme.colors.press, color: theme.colors.ink, borderRadius: theme.radii.button },
        style,
      ]}
    />
  );
}

const styles = StyleSheet.create({
  field: { minHeight: 50, paddingHorizontal: 16 },
});
