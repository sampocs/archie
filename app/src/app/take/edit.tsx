import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Keyboard, Pressable, Switch, View } from "react-native";

import { saveTake } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { canSaveTake } from "@/takes/editor";
import { KindToggle } from "@/takes/KindToggle";
import { editorHint, editorStart, type TakeKind } from "@/takes/takes";
import { useTakesState } from "@/takes/useTakesData";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { textStyles } from "@/theme/type";
import { useTheme } from "@/theme/useTheme";
import { haptic } from "@/ui/haptics";

const MAX_TITLE_LENGTH = 200;

export default function TakeEditorScreen() {
  const router = useRouter();
  const theme = useTheme();
  const { id } = useLocalSearchParams<{ id?: string }>();
  const { takes, loaded } = useTakesState();
  const take = id ? (takes.find((candidate) => candidate.id === id) ?? null) : null;

  const [kind, setKind] = useState<TakeKind>("talking_point");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [clean, setClean] = useState(false);
  const seeded = useRef(false);
  const ready = id ? loaded && take !== null : true;

  // Seed once: later pulls must not overwrite what is being typed.
  useEffect(() => {
    if (seeded.current || !ready) return;
    seeded.current = true;
    const start = editorStart(take);
    setKind(start.kind);
    setTitle(start.title);
    setBody(start.body);
    setClean(start.clean);
  }, [ready, take]);

  if (!ready) return null;

  const canSave = canSaveTake({ title, body });

  function save(): void {
    if (!canSave) return;
    Keyboard.dismiss();
    saveTake(db, { id: take?.id ?? null, kind, title, body, clean });
    haptic("success");
    requestSync();
    // Save always closes the editor: a new take lands back on Library, an edit on its page (Decision 7).
    router.back();
  }

  return (
    <Screen
      title={take ? "Edit take" : "New take"}
      sheet
      headerRight={
        // The header sits above the keyboard, so typing never hides Save.
        <View style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.lg }}>
          <Pressable testID="editor-cancel" onPress={() => router.back()} hitSlop={12}>
            <Text tone="ink2">Cancel</Text>
          </Pressable>
          <Pressable
            testID="editor-save"
            disabled={!canSave}
            onPress={save}
            hitSlop={8}
            style={{
              backgroundColor: theme.colors.chrome,
              borderRadius: 16,
              paddingHorizontal: 14,
              paddingVertical: 6,
              opacity: canSave ? 1 : 0.35,
            }}
          >
            <Text variant="headline" style={{ color: theme.colors.onChrome }}>
              Save
            </Text>
          </Pressable>
        </View>
      }
    >
      <View testID="take-editor" style={{ gap: 12 }}>
        <KindToggle value={kind} onChange={setKind} testIDPrefix="editor-kind" />
        <TextField
          testID="editor-title"
          value={title}
          onChangeText={setTitle}
          placeholder="Title"
          maxLength={MAX_TITLE_LENGTH}
          returnKeyType="next"
          style={textStyles.headline}
        />
        <TextField
          testID="editor-body"
          value={body}
          onChangeText={setBody}
          placeholder="Write it out, or dictate with the keyboard's mic"
          multiline
          scrollEnabled={false}
          style={{ minHeight: 250, textAlignVertical: "top", paddingTop: 14, paddingBottom: 14 }}
        />
        {/* The whole row toggles, not just the small switch. */}
        <Pressable
          testID="editor-clean-row"
          onPress={() => setClean(!clean)}
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 12,
            backgroundColor: theme.colors.surface,
            borderColor: theme.colors.line,
            borderWidth: 1,
            borderRadius: 14,
            padding: 14,
          }}
        >
          <View style={{ flex: 1, gap: 2 }}>
            <Text variant="headline">Clean it up</Text>
            <Text variant="secondary" tone="ink3">
              Archie turns this into a short take with main points. Your words and claims only.
            </Text>
          </View>
          <Switch
            testID="editor-clean"
            value={clean}
            onValueChange={setClean}
            trackColor={{ true: theme.signals.gotIt }}
          />
        </Pressable>
        <Text testID="editor-hint" variant="secondary" tone="ink3">
          {editorHint(take)}
        </Text>
      </View>
    </Screen>
  );
}
