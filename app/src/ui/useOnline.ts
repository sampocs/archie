import * as Network from "expo-network";
import { useSyncExternalStore } from "react";

// Dev only: `archie://dev/offline?on=1` forces offline and `?on=0` back to the real state, since the simulator is never
// offline. Release builds never set it.
let offlineOverride = false;
const listeners = new Set<() => void>();

export function setOfflineOverride(offline: boolean): void {
  if (!__DEV__) return;
  offlineOverride = offline;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Whether the phone is connected and the internet is reachable (unknown counts as online), or false under the dev override. */
export function useOnline(): boolean {
  const network = Network.useNetworkState();
  const overridden = useSyncExternalStore(subscribe, () => offlineOverride);

  return !overridden && network.isConnected !== false && network.isInternetReachable !== false;
}
