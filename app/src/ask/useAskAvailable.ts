import { useEffect, useSyncExternalStore } from "react";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";
import { useOnline } from "@/ui/useOnline";

import { getAskAvailable, loadAskAvailable, subscribeAskAvailable } from "./askAvailableStore";

/**
 * true / false once `/me` answered; null while unknown (offline at launch), which the screens treat as available.
 * Every instance reads the shared store, and an unknown answer is fetched again when the phone comes back online, so a
 * screen that stays mounted (Today) picks up the answer without a relaunch.
 */
export function useAskAvailable(): boolean | null {
  const { sessionKey } = useSession();
  const online = useOnline();
  const available = useSyncExternalStore(subscribeAskAvailable, () => getAskAvailable(sessionKey));

  useEffect(() => {
    if (!sessionKey || !online || available !== null) return;
    void loadAskAvailable(sessionKey, async () => {
      const me = (await apiFetch("/me", { sessionKey })) as { is_whitelisted?: boolean };
      return me.is_whitelisted === true;
    });
  }, [sessionKey, online, available]);

  return available;
}
