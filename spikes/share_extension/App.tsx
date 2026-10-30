import { useEffect, useState } from "react";
import { FlatList, SafeAreaView, StyleSheet, Text, View } from "react-native";
import * as Linking from "expo-linking";

import { decodeRecord, type SharedRecord } from "./shared";

// Lists every share the extension handed back via deep link, so all test shares can be compared in one place
export default function App() {
  const [records, setRecords] = useState<SharedRecord[]>([]);

  useEffect(() => {
    const receive = (url: string | null) => {
      const record = url ? Linking.parse(url).queryParams?.record : undefined;
      if (typeof record !== "string") {
        return;
      }
      // A cold start can deliver the same link through both getInitialURL and the url event
      try {
        const parsed = decodeRecord(record);
        console.log("[share-spike] received", JSON.stringify(parsed));
        setRecords((existing) =>
          existing.some((entry) => entry.receivedAt === parsed.receivedAt) ? existing : [parsed, ...existing],
        );
      } catch (error) {
        console.warn("[share-spike] unreadable record", url, error);
      }
    };

    Linking.getInitialURL().then(receive);
    const subscription = Linking.addEventListener("url", (event) => receive(event.url));
    return () => subscription.remove();
  }, []);

  return (
    <SafeAreaView style={styles.container}>
      <Text style={styles.heading}>Received shares ({records.length})</Text>
      <FlatList
        data={records}
        keyExtractor={(record) => record.receivedAt}
        ListEmptyComponent={<Text style={styles.empty}>Share a link from Spotify, X, YouTube, or Safari and tap “Save to app”.</Text>}
        renderItem={({ item }) => (
          <View style={styles.card}>
            <Text style={styles.source}>{item.payload.source}</Text>
            <Text style={styles.mono} selectable>url: {item.payload.rawUrl ?? "—"}</Text>
            <Text style={styles.mono} selectable>text: {item.payload.rawText ?? "—"}</Text>
            <Text style={styles.mono}>
              fetch: {item.probe ? `${item.probe.status ?? "failed"} · ${item.probe.millis} ms · ${item.probe.title ?? item.probe.error ?? "no title"}` : "—"}
            </Text>
          </View>
        )}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#fff" },
  heading: { fontSize: 22, fontWeight: "600", padding: 16 },
  empty: { padding: 16, color: "#666" },
  card: { marginHorizontal: 16, marginBottom: 12, padding: 12, borderRadius: 10, backgroundColor: "#f3f3f3", gap: 4 },
  source: { fontWeight: "600", textTransform: "uppercase", fontSize: 12, color: "#555" },
  mono: { fontFamily: "Menlo", fontSize: 12 },
});
