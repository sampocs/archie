import { eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import * as Network from "expo-network";
import { useFocusEffect } from "expo-router";
import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { db } from "@/db/client";
import * as schema from "@/db/schema";
import { useCompletedSyncRuns } from "@/sync/useSync";
import { useNow } from "@/ui/useNow";

import { mergeProblems, parseProblems, type Problem } from "./problems";

/**
 * What needs the owner's attention: the server's `/problems` plus a local "can't reach the server" problem. The server's
 * answer is fetched when the screen gains focus and after each sync completes, and kept in memory only. A failed fetch
 * keeps the previous answer, and offline nothing is shown at all.
 */
export function useProblems(): Problem[] {
  const session = useSession();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  const now = useNow();
  const completedRuns = useCompletedSyncRuns();
  const [focusCount, setFocusCount] = useState(0);
  const [serverProblems, setServerProblems] = useState<Problem[]>([]);
  const { data: stateRows } = useLiveQuery(
    db.select({ contactAt: schema.syncState.lastServerContactAt }).from(schema.syncState).where(eq(schema.syncState.id, 1)),
  );

  useFocusEffect(useCallback(() => setFocusCount((count) => count + 1), []));

  useEffect(() => {
    // A signed-out phone must not keep the last user's problems.
    if (!session.sessionKey) {
      setServerProblems([]);
      return;
    }
    if (!online) return;

    const controller = new AbortController();
    apiFetch("/problems", { sessionKey: session.sessionKey, signal: controller.signal })
      .then((body) => setServerProblems(parseProblems(body)))
      // Keep the previous list: one failed request says nothing about whether the problems went away.
      .catch(() => undefined);
    return () => controller.abort();
  }, [focusCount, completedRuns, online, session.sessionKey]);

  return mergeProblems({
    serverProblems,
    lastServerContactAt: stateRows[0]?.contactAt ?? null,
    online,
    now,
  });
}
