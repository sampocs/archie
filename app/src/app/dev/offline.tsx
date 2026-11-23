import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";

import { setOfflineOverride } from "@/ui/useOnline";

// `archie://dev/offline?on=1` makes the note footer and Today's banner see the phone as offline; `?on=0` ends it. For
// Maestro, since the simulator is never offline. Release builds bounce to the app root, so the link does nothing there.
export default function DevOffline() {
  if (!__DEV__) return <Redirect href="/" />;
  return <DevOfflineInner />;
}

function DevOfflineInner() {
  const router = useRouter();
  const { on } = useLocalSearchParams<{ on?: string }>();

  useEffect(() => {
    setOfflineOverride(on === "1");
    if (router.canGoBack()) router.back();
    else router.replace("/");
    // The link is fixed for this route instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
