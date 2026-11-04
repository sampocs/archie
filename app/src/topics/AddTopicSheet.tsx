import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";

import { addTopic } from "@/db/actions";
import { db } from "@/db/client";
import type { TopicRow } from "@/library/join";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { BottomSheet } from "@/ui/BottomSheet";
import { haptic } from "@/ui/haptics";

import { DOMAINS, type DomainName } from "./domains";
import { slugify, topicNameError } from "./topicName";

// "Other" is the catch-all, so it goes last.
const CHOICES: DomainName[] = [...DOMAINS.filter((domain) => domain !== "Other"), "Other"];

type AddTopicSheetProps = { topics: TopicRow[]; visible: boolean; onClose: () => void };

/** Add a topic the user wants to understand: pick its domain, name it. */
export function AddTopicSheet({ topics, visible, onClose }: AddTopicSheetProps) {
  const theme = useTheme();
  const [domain, setDomain] = useState<DomainName>(CHOICES[0]);
  const [name, setName] = useState("");
  const [touched, setTouched] = useState(false);
  const error = topicNameError(name, topics);

  useEffect(() => {
    if (!visible) return;
    setName("");
    setTouched(false);
  }, [visible]);

  function save(): void {
    addTopic(db, { domain, name });
    haptic("success");
    requestSync();
    onClose();
  }

  return (
    <BottomSheet visible={visible} onClose={onClose} testID="add-topic-sheet">
      <Text variant="headline">Add a topic</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
        {CHOICES.map((choice) => {
          const selected = choice === domain;
          return (
            <Pressable
              key={choice}
              testID={`add-topic-domain-${slugify(choice)}`}
              onPress={() => {
                haptic("selection");
                setDomain(choice);
              }}
              style={{
                paddingHorizontal: theme.spacing.md,
                paddingVertical: theme.spacing.sm,
                borderRadius: theme.radii.chip,
                backgroundColor: selected ? theme.colors.chrome : theme.colors.press,
              }}
            >
              <Text variant="secondary" tone={selected ? "onChrome" : "ink"}>
                {choice}
              </Text>
            </Pressable>
          );
        })}
      </View>
      <TextField
        testID="add-topic-name"
        placeholder="e.g. Monetary plumbing"
        value={name}
        onChangeText={(text) => {
          setTouched(true);
          setName(text);
        }}
      />
      {touched && error ? (
        <Text variant="secondary" tone="ink3" testID="add-topic-error">
          {error}
        </Text>
      ) : null}
      <Button testID="add-topic-save" label="Add" disabled={error !== null} onPress={save} />
    </BottomSheet>
  );
}
