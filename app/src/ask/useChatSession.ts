import { randomUUID } from "expo-crypto";
import { useCallback, useEffect, useRef, useState } from "react";

import { UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { requestSync } from "@/sync/useSync";

import { applyEvent, EMPTY_LIVE, endOfStream, handedOver, type LiveAnswer, type PendingQuestion } from "./sections";
import { streamAnswer } from "./stream";
import type { AboutKind, MessageRow } from "./types";

export type { PendingQuestion };

/**
 * Sending a question and showing its answer as it streams. Leaving the chat lets the stream run on: the server saves
 * the answer and the next pull brings it. The overlay stays until the pulled rows hold the question
 * and its answer (or, for a failed stream, a later assistant row), and the returned `pending` is already null on the
 * render where they land, so nothing flickers or shows twice.
 */
export function useChatSession(input: {
  conversationId: string;
  messages: MessageRow[];
  about: { kind: AboutKind; id: string } | null;
}): { pending: PendingQuestion | null; send: (text: string, webSearch: boolean) => void } {
  const { sessionKey } = useSession();
  const [overlay, setOverlay] = useState<PendingQuestion | null>(null);
  const pending = overlay && !handedOver(overlay, input.messages) ? overlay : null;
  // Leaving the chat does not abort the stream: the server finishes and saves the answer, and the next pull brings it.
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Drop the overlay's state once the pulled rows have taken over (`pending` already hides it during that render).
  useEffect(() => {
    if (overlay && handedOver(overlay, input.messages)) setOverlay(null);
  }, [input.messages, overlay]);

  const send = useCallback(
    (text: string, webSearch: boolean) => {
      const question = text.trim();
      // A failed question may be sent again (Try again); one still answering may not.
      if (!question || !sessionKey || (pending && !pending.live.failed)) return;

      const userMessageId = randomUUID();
      const update = (change: (live: LiveAnswer) => LiveAnswer) => {
        if (!mounted.current) return;
        setOverlay((current) =>
          current && current.userMessageId === userMessageId ? { ...current, live: change(current.live) } : current,
        );
      };
      setOverlay({ userMessageId, text: question, webSearch, live: EMPTY_LIVE });

      streamAnswer({
        conversationId: input.conversationId,
        // The server reads `about` only when this question creates the chat.
        body: { user_message_id: userMessageId, text: question, web_search: webSearch, about: input.messages.length === 0 ? input.about : null },
        sessionKey,
        onEvent: (event) => update((live) => applyEvent(live, event)),
      })
        .then(() => update(endOfStream))
        .catch((error) => {
          if (error instanceof UnauthorizedError) void clearSession();
          update((live) => ({ ...live, failed: true, searching: null }));
        })
        .finally(() => requestSync());
    },
    [input.conversationId, input.messages.length, input.about, pending, sessionKey],
  );

  return { pending, send };
}
