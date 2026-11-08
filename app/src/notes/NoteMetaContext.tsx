import { createContext, ReactNode, useContext, useMemo } from "react";

import type { LibrarySource } from "@/library/join";

import { noteMeta, refresherQueue } from "./refresher";

type NoteMetaState = { queue: LibrarySource[]; now: Date };

const NoteMetaContext = createContext<NoteMetaState | null>(null);

/** Computes the refresher queue once for every Library row beneath it, instead of once per row. */
export function NoteMetaProvider({ sources, now, children }: { sources: LibrarySource[]; now: Date; children: ReactNode }) {
  const queue = useMemo(() => refresherQueue(sources), [sources]);
  const state = useMemo(() => ({ queue, now }), [queue, now]);

  return <NoteMetaContext.Provider value={state}>{children}</NoteMetaContext.Provider>;
}

/** A note's Library meta line ("Notes · up next"); undefined for other kinds, or outside a provider. */
export function useNoteMeta(source: LibrarySource | null): string | undefined {
  const state = useContext(NoteMetaContext);
  if (source?.kind !== "note" || state === null) return undefined;
  return noteMeta(source, state.queue, state.now);
}
