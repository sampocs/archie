import Storage from "expo-sqlite/kv-store";
import { useCallback, useState } from "react";

import { asBrowseMode, type BrowseMode } from "./browse";

// Phone-only, so it lives in the key-value store rather than a synced table.
export const BROWSE_MODE_KEY = "review.browseMode";

/** The Review tab's Topics | Items | Missed choice: the owner's last one, kept on this phone. */
export function useBrowseMode(): [BrowseMode, (mode: BrowseMode) => void] {
  const [mode, setMode] = useState<BrowseMode>(() => asBrowseMode(Storage.getItemSync(BROWSE_MODE_KEY)));
  const choose = useCallback((next: BrowseMode) => {
    setMode(next);
    Storage.setItemSync(BROWSE_MODE_KEY, next);
  }, []);
  return [mode, choose];
}
