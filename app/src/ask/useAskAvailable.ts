import { useEffect, useState } from "react";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";

// One `/me` per session key: whether the owner's keys pay for this account's Ask doesn't change while signed in.
let cached: { key: string; whitelisted: boolean } | null = null;

/** true / false once `/me` answered; null while unknown (offline at launch), which the screens treat as available. */
export function useAskAvailable(): boolean | null {
  const { sessionKey } = useSession();
  const [available, setAvailable] = useState<boolean | null>(
    cached && cached.key === sessionKey ? cached.whitelisted : null,
  );

  useEffect(() => {
    if (!sessionKey) return;
    if (cached?.key === sessionKey) {
      setAvailable(cached.whitelisted);
      return;
    }
    let live = true;
    apiFetch("/me", { sessionKey })
      .then((me) => {
        const whitelisted = (me as { is_whitelisted?: boolean }).is_whitelisted === true;
        cached = { key: sessionKey, whitelisted };
        if (live) setAvailable(whitelisted);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [sessionKey]);

  return available;
}
