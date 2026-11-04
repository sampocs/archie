import { useEffect, useState } from "react";
import { Pressable, View } from "react-native";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { chooseTopics, type ChosenTopic } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Card } from "@/theme/components/Card";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { TextField } from "@/theme/components/TextField";
import { useTheme } from "@/theme/useTheme";
import { asDomain, type DomainName } from "@/topics/domains";
import { addOwn, togglePick } from "@/topics/pickerState";
import { slugify } from "@/topics/topicName";
import { haptic } from "@/ui/haptics";
import { Kicker } from "@/ui/Kicker";

type StarterDomain = { domain: string; topics: string[] };
type Starter = { status: "loading" } | { status: "failed" } | { status: "ready"; domains: StarterDomain[] };

// Shown before the tabs while the user hasn't chosen topics yet (the gate lives in the root layout).
export default function TopicPicker() {
  const session = useSession();
  const [starter, setStarter] = useState<Starter>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [picked, setPicked] = useState<ChosenTopic[]>([]);

  useEffect(() => {
    if (session.status !== "signedIn") return;
    setStarter({ status: "loading" });
    apiFetch("/topics/starter", { sessionKey: session.sessionKey })
      .then((body) => setStarter({ status: "ready", domains: (body as { domains: StarterDomain[] }).domains }))
      .catch(() => setStarter({ status: "failed" }));
  }, [session.status, session.sessionKey, attempt]);

  function submit(): void {
    chooseTopics(db, picked);
    haptic("success");
    requestSync();
  }

  return (
    <Screen title="Pick your topics">
      <Text tone="ink2">
        Archie files what you save under these. Pick the ones you want to understand; you can change them any time.
      </Text>

      {starter.status === "loading" ? <Text tone="ink3">Loading topics…</Text> : null}
      {starter.status === "failed" ? (
        <View style={{ gap: 12 }}>
          <Text tone="ink3">Needs a connection.</Text>
          <Button testID="picker-retry" label="Try again" variant="secondary" onPress={() => setAttempt(attempt + 1)} />
        </View>
      ) : null}
      {starter.status === "ready"
        ? starter.domains.map((entry) => (
            <DomainCard key={entry.domain} entry={entry} picked={picked} onChange={setPicked} />
          ))
        : null}

      <Button
        testID="picker-continue"
        label={`Continue · ${picked.length}`}
        disabled={picked.length === 0}
        onPress={submit}
      />
    </Screen>
  );
}

type DomainCardProps = { entry: StarterDomain; picked: ChosenTopic[]; onChange: (picked: ChosenTopic[]) => void };

function DomainCard({ entry, picked, onChange }: DomainCardProps) {
  const theme = useTheme();
  const domain = asDomain(entry.domain);
  const slug = slugify(domain);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const ownPicks = picked.filter((pick) => pick.domain === domain && pick.origin === "user");

  function saveOwn(): void {
    const result = addOwn(picked, domain, draft);
    setError(result.error);
    if (result.error) return;

    haptic("selection");
    onChange(result.picked);
    setDraft("");
    setAdding(false);
  }

  return (
    <Card style={{ gap: theme.spacing.md }}>
      <Kicker domain={domain} />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: theme.spacing.sm }}>
        {entry.topics.map((name) => (
          <Chip
            key={name}
            testID={`pick-${slug}-${slugify(name)}`}
            label={name}
            domain={domain}
            selected={isPicked(picked, domain, name)}
            onPress={() => {
              haptic("selection");
              onChange(togglePick(picked, { domain, name, origin: "starter" }));
            }}
          />
        ))}
        {ownPicks.map((pick) => (
          <Chip
            key={pick.name}
            testID={`pick-${slug}-${slugify(pick.name)}`}
            label={pick.name}
            domain={domain}
            selected
            onPress={() => onChange(togglePick(picked, pick))}
          />
        ))}
      </View>

      {adding ? (
        <View style={{ gap: theme.spacing.sm }}>
          <TextField
            testID={`pick-add-${slug}-input`}
            placeholder="Topic name"
            value={draft}
            onChangeText={setDraft}
            autoFocus
            returnKeyType="done"
            onSubmitEditing={saveOwn}
          />
          {error ? <Text tone="ink3">{error}</Text> : null}
          <Button testID={`pick-add-${slug}-save`} label="Add" variant="secondary" onPress={saveOwn} />
        </View>
      ) : (
        <Pressable testID={`pick-add-${slug}`} onPress={() => setAdding(true)} hitSlop={8}>
          <Text tone="ink2">＋ Add your own</Text>
        </Pressable>
      )}
    </Card>
  );
}

type ChipProps = { testID: string; label: string; domain: DomainName; selected: boolean; onPress: () => void };

function Chip({ testID, label, domain, selected, onPress }: ChipProps) {
  const theme = useTheme();
  const tint = theme.domains[domain];

  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      accessibilityState={{ selected }}
      style={{
        backgroundColor: selected ? tint : theme.colors.press,
        borderRadius: theme.radii.chip,
        paddingHorizontal: theme.spacing.md,
        paddingVertical: theme.spacing.sm,
      }}
    >
      <Text variant="body" tone={selected ? "onChrome" : "ink"}>
        {label}
      </Text>
    </Pressable>
  );
}

function isPicked(picked: ChosenTopic[], domain: DomainName, name: string): boolean {
  return picked.some((pick) => pick.domain === domain && pick.name === name);
}
