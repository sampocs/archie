import { useEffect, useRef } from "react";

import { writeSharedCollections } from "./sharedCollections";
import { encodeSharedCollections } from "./sharedCollectionsFormat";
import { useCollectionsData } from "./useCollectionsData";

/**
 * Keeps the share extension's list of collections (names and ids, in tile order) in step with the local database.
 * Mounted only while signed in; renders nothing.
 */
export function CollectionsMirror() {
  const collections = useCollectionsData();
  const lastWritten = useRef<string | null>(null);
  // Writes run one after another so the last list always lands last (the first live result is an empty list).
  const chain = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    const list = collections.map(({ id, name }) => ({ id, name }));
    const encoded = encodeSharedCollections(list);
    // Posts change far more often than names; only a different list is worth a Keychain write.
    if (encoded === lastWritten.current) return;
    lastWritten.current = encoded;
    // A failed write: the share sheet then shows the last list it saw; forgetting what was written lets the next
    // change retry.
    chain.current = chain.current
      .then(() => writeSharedCollections(list))
      .catch(() => {
        if (lastWritten.current === encoded) lastWritten.current = null;
      });
  }, [collections]);

  return null;
}
