import { Switch, View } from "react-native";

import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";

import { CaptureChoice, EMPTY_CHOICE, Intent, Reaction } from "./types";

type CaptureOptionsProps = { value: CaptureChoice; onChange: (choice: CaptureChoice) => void };

const REACTIONS: { reaction: Reaction; label: string }[] = [
  { reaction: "easy", label: "Easy" },
  { reaction: "mostly", label: "Mostly followed" },
  { reaction: "lost", label: "Parts lost me" },
];

// Shared by the app's Add screen and the share extension, so it only uses theme components and react-native.
export function CaptureOptions({ value, onChange }: CaptureOptionsProps) {
  // Switching intent drops the other intent's answers: the server rejects a reaction on a queued source.
  const chooseIntent = (intent: Intent) => onChange(intent === value.intent ? value : { ...EMPTY_CHOICE, intent });

  return (
    <View style={{ gap: 12 }}>
      <Button
        testID="intent-finished"
        label="Finished"
        variant={value.intent === "finished" ? "primary" : "secondary"}
        onPress={() => chooseIntent("finished")}
      />
      <Button
        testID="intent-queue"
        label="Queue it"
        variant={value.intent === "queue" ? "primary" : "secondary"}
        onPress={() => chooseIntent("queue")}
      />

      {value.intent === "finished" && (
        <View style={{ gap: 12 }}>
          <Text variant="secondary" tone="ink2">
            How'd it go?
          </Text>
          {REACTIONS.map(({ reaction, label }) => (
            <Button
              key={reaction}
              testID={`reaction-${reaction}`}
              label={label}
              variant={value.reaction === reaction ? "primary" : "secondary"}
              onPress={() => onChange({ ...value, reaction: value.reaction === reaction ? null : reaction })}
            />
          ))}
          <TextField
            testID="capture-note"
            value={value.note}
            onChangeText={(note) => onChange({ ...value, note })}
            placeholder="Anything confusing?"
            maxLength={2000}
          />
        </View>
      )}

      {value.intent === "queue" && (
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <Text>Prep me</Text>
          <Switch testID="prep-me" value={value.prepMe} onValueChange={(prepMe) => onChange({ ...value, prepMe })} />
        </View>
      )}
    </View>
  );
}
