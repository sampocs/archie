import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";

import { apiFetch } from "@/api/client";
import { setSessionKey } from "@/auth/session";

// `archie://dev/login` signs in as the test user without Apple, for Maestro and local dev. Release builds
// bounce straight to the app root, so the link does nothing there. `?whitelisted=1` also makes the test user the
// owner's, so the worker spends the owner's Anthropic key on its sources (flows that wait for a summary need it). Topics are seeded for the test user so flows skip the topic picker;
// `?picker=1` leaves them unseeded to exercise it, and `?sub=<apple_sub>` signs in as a distinct user.
export default function DevLogin() {
  if (!__DEV__) return <Redirect href="/" />;
  return <DevLoginInner />;
}

let signedInThisLaunch = false;

function DevLoginInner() {
  const router = useRouter();
  const { whitelisted, picker, sub } = useLocalSearchParams<{ whitelisted?: string; picker?: string; sub?: string }>();

  useEffect(() => {
    // Signing in rebuilds the stack, which can mount this route again without the link's params; that repeat hands
    // over to the app's own routing instead of signing in again as the plain test user. A new link (with params, as
    // flows that switch to the owner's user send) still signs in.
    const isBareRepeat = signedInThisLaunch && whitelisted === undefined && picker === undefined && sub === undefined;
    if (isBareRepeat) {
      router.replace("/");
      return;
    }
    signedInThisLaunch = true;

    apiFetch("/test/session", {
      method: "POST",
      body: { is_whitelisted: whitelisted === "1", seed_topics: picker !== "1", ...(sub ? { apple_sub: sub } : {}) },
      sessionKey: null,
    })
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
