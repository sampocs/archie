import { useSync } from "./useSync";

// Mounted once in the root layout; renders nothing, just runs the sync triggers.
export function SyncRoot(props: { sessionKey: string | null; onUnauthorized: () => void }) {
  useSync(props);
  return null;
}
