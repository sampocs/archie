import * as AppleAuthentication from "expo-apple-authentication";
import { useState } from "react";
import { StyleSheet, View } from "react-native";

import { signInWithApple } from "@/auth/session";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";

const CANCELED_CODE = "ERR_REQUEST_CANCELED";

export default function SignIn() {
  const theme = useTheme();
  const [error, setError] = useState<string | null>(null);

  async function onPress() {
    setError(null);
    try {
      await signInWithApple();
    } catch (caught) {
      // Backing out of Apple's sheet is not a failure.
      if ((caught as { code?: string }).code === CANCELED_CODE) return;
      setError("Couldn't sign in. Check your connection and try again.");
    }
  }

  return (
    <View style={[styles.root, { backgroundColor: theme.colors.bg, padding: theme.spacing.gutterCards }]}>
      <Text variant="largeTitle">Archie</Text>
      <AppleAuthentication.AppleAuthenticationButton
        buttonType={AppleAuthentication.AppleAuthenticationButtonType.SIGN_IN}
        buttonStyle={AppleAuthentication.AppleAuthenticationButtonStyle.BLACK}
        cornerRadius={theme.radii.button}
        style={styles.button}
        testID="apple-sign-in"
        onPress={onPress}
      />
      {error ? <Text tone="ink2">{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: "center", justifyContent: "center", gap: 24 },
  button: { width: 280, height: 50 },
});
