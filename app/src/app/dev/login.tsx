import { Redirect, useRouter } from "expo-router";
import { useEffect } from "react";

import { apiFetch } from "@/api/client";
import { setSessionKey } from "@/auth/session";

// `archie://dev/login` signs in as the test user without Apple, for Maestro and local dev. Release builds
// bounce straight to the app root, so the link does nothing there.
export default function DevLogin() {
  if (!__DEV__) return <Redirect href="/" />;
  return <DevLoginInner />;
}

function DevLoginInner() {
  const router = useRouter();

  useEffect(() => {
    apiFetch("/test/session", { method: "POST", body: {}, sessionKey: null })
      .then(async (response) => {
        await setSessionKey((response as { session_key: string }).session_key);
        router.replace("/(tabs)/library");
      })
      .catch(() => router.replace("/sign-in"));
  }, [router]);

  return null;
}
