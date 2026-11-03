import { count, eq } from "drizzle-orm";
import { useLiveQuery } from "drizzle-orm/expo-sqlite";
import * as Network from "expo-network";
import { useEffect, useRef } from "react";
import { AppState } from "react-native";

import { db } from "@/db/client";
import * as schema from "@/db/schema";

import { createSyncScheduler, runSync } from "./engine";
import { createApiTransport, createDbSyncStore } from "./transport";

const POLL_INTERVAL_MS = 60_000;

// The active hook instance registers its trigger here so non-React callers (e.g. after addSource) can request a sync.
let activeTrigger: (() => void) | null = null;

export function requestSync(): void {
  activeTrigger?.();
}

type UseSyncArgs = { sessionKey: string | null; onUnauthorized: () => void };

export function useSync({ sessionKey, onUnauthorized }: UseSyncArgs): void {
  // Refs keep the long-lived triggers pointed at the latest values without re-subscribing.
  const sessionKeyRef = useRef(sessionKey);
  const onUnauthorizedRef = useRef(onUnauthorized);
  sessionKeyRef.current = sessionKey;
  onUnauthorizedRef.current = onUnauthorized;

  const hasSession = sessionKey !== null;

  useEffect(() => {
    if (!hasSession) return;

    const store = createDbSyncStore(db);
    const transport = createApiTransport(() => sessionKeyRef.current);
    const trigger = createSyncScheduler(async () => {
      const outcome = await runSync(store, transport);
      if (outcome === "unauthorized") onUnauthorizedRef.current();
    });
    const fire = () => void trigger().catch(() => undefined);

    activeTrigger = fire;
    fire();

    const appStateSub = AppState.addEventListener("change", (state) => {
      if (state === "active") fire();
    });
    const networkSub = Network.addNetworkStateListener((state) => {
      if (state.isConnected) fire();
    });
    const interval = setInterval(() => {
      if (AppState.currentState === "active") fire();
    }, POLL_INTERVAL_MS);

    return () => {
      if (activeTrigger === fire) activeTrigger = null;
      appStateSub.remove();
      networkSub.remove();
      clearInterval(interval);
    };
  }, [hasSession]);
}

export function useSyncStatus(): { waiting: number; offline: boolean } {
  const { data: waitingRows } = useLiveQuery(
    db.select({ waiting: count() }).from(schema.outbox).where(eq(schema.outbox.status, "pending")),
  );
  const { data: stateRows } = useLiveQuery(
    db.select({ failed: schema.syncState.lastPushFailed }).from(schema.syncState).where(eq(schema.syncState.id, 1)),
  );

  return { waiting: waitingRows[0]?.waiting ?? 0, offline: stateRows[0]?.failed === 1 };
}
