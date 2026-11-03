import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";

import type { Intent, Reaction } from "@/capture/types";
import { addSource } from "@/db/actions";
import { db } from "@/db/client";
import { requestSync } from "@/sync/useSync";

const INTENTS: readonly string[] = ["finished", "queue"] satisfies Intent[];
const REACTIONS: readonly string[] = ["easy", "mostly", "lost"] satisfies Reaction[];

// Target of archie://share?url=…&intent=…, opened by the share extension when it can't reach the backend.
// With no session the root layout shows sign-in instead of this route.
export default function ShareScreen() {
  const router = useRouter();
  const { url, intent, reaction, note, prep_me: prepMe } = useLocalSearchParams<{
    url?: string;
    intent?: string;
    reaction?: string;
    note?: string;
    prep_me?: string;
  }>();

  useEffect(() => {
    async function save(): Promise<void> {
      if (url && intent && INTENTS.includes(intent)) {
        const isFinished = intent === "finished";
        await addSource(db, {
          url,
          intent: intent as Intent,
          // Reaction and note belong to finished only; the server rejects them on a queued source.
          reaction: isFinished && reaction && REACTIONS.includes(reaction) ? (reaction as Reaction) : null,
          note: isFinished ? note : null,
          prepMe: !isFinished && prepMe === "1",
        });
        requestSync();
      }
      router.replace("/(tabs)/library");
    }

    void save();
    // The params are fixed for this route instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
