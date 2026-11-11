import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect } from "react";

import { saveToCollection } from "@/collections/saveToCollection";
import { addBook, addSource } from "@/db/actions";
import { db } from "@/db/client";
import {
  sharedBookFromParams,
  sharedCollectionItemFromParams,
  sharedSourceFromParams,
  type ShareParams,
} from "@/share/deepLink";
import { requestSync } from "@/sync/useSync";

// Target of archie://share?url=…&intent=… (or ?book=1&… for a book), opened by the share extension when it can't
// reach the backend.
// With no session the root layout shows sign-in instead of this route.
export default function ShareScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<ShareParams>();

  useEffect(() => {
    async function save(): Promise<void> {
      const sharedBook = sharedBookFromParams(params);
      const sharedItem = sharedCollectionItemFromParams(params);
      const shared = sharedSourceFromParams(params);
      if (sharedBook) {
        // The fallback link carries no author or cover, so the book is added without them.
        addBook(db, { ...sharedBook, author: null, imageUrl: null });
        requestSync();
      } else if (sharedItem) {
        saveToCollection(sharedItem);
        requestSync();
      } else if (shared) {
        await addSource(db, shared);
        requestSync();
      }
      router.replace("/(tabs)/library");
    }

    void save();
    // The params are fixed for this route instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}
