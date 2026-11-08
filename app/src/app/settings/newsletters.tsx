import { eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import { useRouter } from "expo-router";
import { View } from "react-native";

import { setSenderStatus } from "@/db/actions";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { requestSync } from "@/sync/useSync";
import { Button } from "@/theme/components/Button";
import { Screen } from "@/theme/components/Screen";
import { Text } from "@/theme/components/Text";
import { useTheme } from "@/theme/useTheme";
import { GroupedList } from "@/ui/GroupedList";
import { haptic } from "@/ui/haptics";

/** Settings → Blocked senders: the newsletter senders the owner blocked, A–Z, each with Unblock. */
export default function BlockedSendersScreen() {
  const router = useRouter();
  const theme = useTheme();
  const { data: blocked } = useLiveQuery(
    db.select().from(schema.newsletterSenders).where(eq(schema.newsletterSenders.status, "blocked")),
  );
  // Sorted here, not in SQL, so the order ignores case like the rest of Settings.
  const sorted = [...blocked].sort((first, second) => first.label.localeCompare(second.label));

  return (
    <Screen title="Blocked senders" onBack={router.back}>
      {sorted.length === 0 ? (
        <Text testID="blocked-senders-empty" tone="ink2">
          No blocked senders.
        </Text>
      ) : (
        <GroupedList>
          {sorted.map((sender) => (
            <View
              key={sender.id}
              style={{ flexDirection: "row", alignItems: "center", gap: theme.spacing.md, paddingVertical: theme.spacing.md }}
            >
              <Text style={{ flex: 1 }}>{sender.label}</Text>
              <Button
                testID={`unblock-${sender.id}`}
                label="Unblock"
                variant="secondary"
                onPress={() => {
                  setSenderStatus(db, sender.id, "allowed");
                  haptic("success");
                  requestSync();
                }}
              />
            </View>
          ))}
        </GroupedList>
      )}
    </Screen>
  );
}
