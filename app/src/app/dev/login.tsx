import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";

import { apiFetch } from "@/api/client";
import { setSessionKey } from "@/auth/session";

// `archie://dev/login` signs in as the test user without Apple, for Maestro and local dev. Release builds
// bounce straight to the app root, so the link does nothing there. `?whitelisted=1` also makes the test user the
// owner's, so the worker spends the owner's Anthropic key on its sources (flows that wait for a summary need it).
export default function DevLogin() {
  if (!__DEV__) return <Redirect href="/" />;
  return <DevLoginInner />;
}

function DevLoginInner() {
  const router = useRouter();
  const { whitelisted } = useLocalSearchParams<{ whitelisted?: string }>();

  useEffect(() => {
    apiFetch("/test/session", { method: "POST", body: { is_whitelisted: whitelisted === "1" }, sessionKey: null })
      .then(async (response) => {
        await setSessionKey((response as { session_key: string }).session_key);
        router.replace("/(tabs)/library");
      })
      .catch(() => router.replace("/sign-in"));
    // The link is fixed for this route instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
