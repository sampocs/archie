import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet } from "react-native";
import { close, openHostApp, Text, View, type InitialProps } from "expo-share-extension";

import { describePayload, encodeRecord, probeUrl, type ProbeResult, type SharedRecord } from "./shared";

// Shows exactly what the sharing app handed over, and checks the extension can reach the network
export default function ShareExtension(props: InitialProps) {
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const payload = describePayload(props);

  useEffect(() => {
    if (payload.url) {
      probeUrl(payload.url).then(setProbe);
    }
  }, [payload.url]);

  const saveToApp = () => {
    const record: SharedRecord = { receivedAt: new Date().toISOString(), payload, probe };
    openHostApp(`received?record=${encodeRecord(record)}`);
  };

  // Saving before the probe finishes would record "no result" and look like a network failure
  const probing = Boolean(payload.url) && probe === null;

  return (
    <View style={styles.container}>
      <Text style={styles.heading}>Shared to Carl</Text>
      <ScrollView style={styles.body}>
        <Field label="url" value={props.url} />
        <Field label="text" value={props.text} />
        <Field label="detected url" value={payload.url} />
        <Field label="source" value={payload.source} />
        <Field
          label="network check"
          value={
            payload.url
              ? probe
                ? `${probe.status ?? "failed"} in ${probe.millis} ms · ${probe.title ?? probe.error ?? "no title"}`
                : "fetching…"
              : "no url to fetch"
          }
        />
      </ScrollView>
      <View style={styles.buttons}>
        <Button label="Close" onPress={close} />
        <Button label={probing ? "Checking…" : "Save to app"} onPress={saveToApp} primary disabled={probing} />
      </View>
    </View>
  );
}

function Field({ label, value }: { label: string; value: string | undefined }) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <Text style={styles.value} selectable>
        {value ?? "—"}
      </Text>
    </View>
  );
}

function Button({
  label,
  onPress,
  primary,
  disabled,
}: {
  label: string;
  onPress: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <Pressable onPress={onPress} disabled={disabled} style={[styles.button, primary && styles.primary, disabled && styles.disabled]}>
      <Text style={[styles.buttonLabel, primary && styles.primaryLabel]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, gap: 12, backgroundColor: "#fff" },
  heading: { fontSize: 20, fontWeight: "600" },
  body: { flex: 1 },
  field: { marginBottom: 12 },
  label: { fontSize: 12, color: "#888", textTransform: "uppercase" },
  value: { fontSize: 14, fontFamily: "Menlo" },
  buttons: { flexDirection: "row", gap: 12 },
  button: { flex: 1, padding: 14, borderRadius: 10, backgroundColor: "#eee", alignItems: "center" },
  primary: { backgroundColor: "#222" },
  buttonLabel: { fontSize: 16 },
  primaryLabel: { color: "#fff" },
  disabled: { opacity: 0.5 },
});
