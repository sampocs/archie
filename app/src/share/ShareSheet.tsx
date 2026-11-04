import { useFonts } from "expo-font";
import { close, openHostApp, type InitialProps } from "expo-share-extension";
import { useEffect, useState } from "react";
import { ScrollView, View } from "react-native";

import { readSharedSessionKey } from "@/auth/keychain";
import { CaptureOptions } from "@/capture/CaptureOptions";
import { CaptureChoice, EMPTY_CHOICE } from "@/capture/types";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { fontAssets } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";

import { resolveShare } from "./resolveShare";
import { buildShareAction, shareDeepLink, submitShare } from "./submit";

type Phase =
  | { name: "editing" }
  | { name: "saving" }
  | { name: "saved" }
  | { name: "unreachable" }
  | { name: "rejected"; reason: string };

const CLOSE_AFTER_SAVED_MS = 1000;

export function ShareSheet(props: InitialProps) {
  const theme = useTheme();
  const { url, title, capture } = resolveShare(props);
  const [choice, setChoice] = useState<CaptureChoice>(EMPTY_CHOICE);
  const [phase, setPhase] = useState<Phase>({ name: "editing" });

  // Text set in a Geist family that isn't registered yet renders invisibly in the extension, so wait
  // for the fonts (or their failure) before drawing anything, as the root layout does in the app.
  const [fontsLoaded, fontError] = useFonts(fontAssets);

  useEffect(() => {
    if (phase.name !== "saved") return;
    const timer = setTimeout(close, CLOSE_AFTER_SAVED_MS);
    return () => clearTimeout(timer);
  }, [phase.name]);

  async function save(): Promise<void> {
    if (!url || !choice.intent) return;
    setPhase({ name: "saving" });

    try {
      const outcome = await submitShare(buildShareAction({ url, choice, capture }), await readSharedSessionKey());
      setPhase(outcome === "saved" ? { name: "saved" } : { name: "unreachable" });
    } catch (error) {
      setPhase({ name: "rejected", reason: error instanceof Error ? error.message : String(error) });
    }
  }

  if (!fontsLoaded && !fontError) return <View style={{ flex: 1, backgroundColor: theme.colors.bg }} />;

  return (
    <View style={{ flex: 1, backgroundColor: theme.colors.bg, padding: theme.spacing.gutterCards, gap: theme.spacing.lg }}>
      {url ? (
        <ShareBody
          {...{ url, title, choice, phase }}
          onChange={setChoice}
          onSave={save}
          onOpenArchie={() => openHostApp(shareDeepLink({ url, choice }))}
        />
      ) : (
        <View style={{ gap: theme.spacing.lg }}>
          <Text variant="headline">Nothing to save here</Text>
          <Button label="Close" onPress={close} />
        </View>
      )}
    </View>
  );
}

type ShareBodyProps = {
  url: string;
  title: string | null;
  choice: CaptureChoice;
  phase: Phase;
  onChange: (choice: CaptureChoice) => void;
  onSave: () => void;
  onOpenArchie: () => void;
};

function ShareBody({ url, title, choice, phase, onChange, onSave, onOpenArchie }: ShareBodyProps) {
  const theme = useTheme();

  if (phase.name === "saved") {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: theme.spacing.md }}>
        <Text variant="largeTitle">✓</Text>
        <Text variant="headline">Saved to Archie</Text>
      </View>
    );
  }

  if (phase.name === "unreachable") {
    return (
      <View style={{ gap: theme.spacing.lg }}>
        <Text variant="headline">Couldn't reach Archie</Text>
        <Text variant="secondary" tone="ink2">
          Open Archie to save this when you're back online or signed in.
        </Text>
        <Button label="Open Archie" onPress={onOpenArchie} />
        <Button label="Close" variant="secondary" onPress={close} />
      </View>
    );
  }

  const busy = phase.name === "saving";
  return (
    <>
      <View style={{ gap: theme.spacing.xs }}>
        <Text variant="headline" numberOfLines={2}>
          {title ?? url}
        </Text>
        <Text variant="secondary" tone="ink3" numberOfLines={1}>
          {url}
        </Text>
      </View>

      <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: theme.spacing.lg }}>
        <CaptureOptions value={choice} onChange={onChange} />
      </ScrollView>

      {phase.name === "rejected" && (
        <Text variant="secondary" tone="ink2">
          {phase.reason}
        </Text>
      )}
      <Button label={busy ? "Saving…" : "Save"} disabled={busy || !choice.intent} onPress={onSave} />
      <Button label="Cancel" variant="secondary" onPress={close} />
    </>
  );
}
