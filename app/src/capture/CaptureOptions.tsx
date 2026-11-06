import type { ReactNode } from "react";
import { Switch, View } from "react-native";

import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";

import { CaptureChoice, chooseIntent, Destination, Reaction } from "./types";

type CaptureOptionsProps = {
  value: CaptureChoice;
  onChange: (choice: CaptureChoice) => void;
  /** The destination picker (dropdown in the app, chips in the extension); the third choice shows only with it. */
  collectionPicker?: ReactNode;
};

const REACTIONS: { reaction: Reaction; label: string }[] = [
  { reaction: "easy", label: "Easy" },
  { reaction: "mostly", label: "Mostly followed" },
  { reaction: "lost", label: "Parts lost me" },
];

// Shared by the app's Add screen and the share extension, so it only uses theme components and react-native.
export function CaptureOptions({ value, onChange, collectionPicker }: CaptureOptionsProps) {
  const selectIntent = (intent: Destination) =>
    onChange(chooseIntent(value, intent, value.collection ?? undefined));

  return (
    <View style={{ gap: 12 }}>
      <Button
        testID="intent-finished"
        label="Finished"
        variant={value.intent === "finished" ? "primary" : "secondary"}
        onPress={() => selectIntent("finished")}
      />
      <Button
        testID="intent-queue"
        label="Queue it"
        variant={value.intent === "queue" ? "primary" : "secondary"}
        onPress={() => selectIntent("queue")}
      />
      {collectionPicker && (
        <Button
          testID="intent-collection"
          label="Save to a collection"
          variant={value.intent === "collection" ? "primary" : "secondary"}
          onPress={() => selectIntent("collection")}
        />
      )}

      {collectionPicker && value.intent === "collection" && collectionPicker}

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
              onPress={() =>
                onChange({
                  ...value,
                  reaction: value.reaction === reaction ? null : reaction,
                })
              }
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
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Text>Queue the primer too</Text>
          <Switch
            testID="queue-primer"
            value={value.queuePrimer}
            onValueChange={(queuePrimer) => onChange({ ...value, queuePrimer })}
          />
        </View>
      )}
    </View>
  );
}
