import * as Network from "expo-network";
import { useEffect, useMemo, useRef, useState } from "react";

import { apiFetch } from "@/api/client";
import { useSession } from "@/auth/session";

import {
  createDebouncer,
  parseSearchResults,
  SEARCH_DEBOUNCE_MS,
  searchView,
  type SearchState,
  type ServerSearchResult,
} from "./serverSearch";

/** The server's search for `query`, 300 ms after typing stops; superseded requests are aborted. */
export function useServerSearch(query: string): {
  view: ReturnType<typeof searchView>;
  results: ServerSearchResult[];
} {
  const session = useSession();
  const network = Network.useNetworkState();
  const online = network.isConnected !== false && network.isInternetReachable !== false;
  const [state, setState] = useState<SearchState>({ status: "idle", results: [] });
  const debouncer = useRef(createDebouncer(SEARCH_DEBOUNCE_MS));

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed || !online || !session.sessionKey) {
      debouncer.current.cancel();
      setState({ status: "idle", results: [] });
      return;
    }

    const controller = new AbortController();
    setState((previous) => ({ status: "loading", results: previous.results }));
    debouncer.current.run(() => {
      apiFetch(`/search?q=${encodeURIComponent(trimmed)}`, { sessionKey: session.sessionKey, signal: controller.signal })
        .then((body) => setState({ status: "ready", results: parseSearchResults(body) }))
        .catch(() => {
          if (!controller.signal.aborted) setState({ status: "failed", results: [] });
        });
    });
    return () => {
      controller.abort();
      debouncer.current.cancel();
    };
  }, [query, online, session.sessionKey]);

  const view = useMemo(() => searchView({ query, online, state }), [query, online, state]);
  return { view, results: state.results };
}
