import { randomUUID } from "expo-crypto";
import { useCallback, useEffect, useRef, useState } from "react";

import { UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { requestSync } from "@/sync/useSync";

import { applyEvent, EMPTY_LIVE, type LiveAnswer } from "./sections";
import { streamAnswer } from "./stream";
import type { AboutKind, MessageRow } from "./types";

export type PendingQuestion = { userMessageId: string; text: string; webSearch: boolean; live: LiveAnswer };

/**
 * Sending a question and showing its answer as it streams. The overlay stays until the pulled rows hold the question
 * and its answer (or the stream failed and the question arrived), so nothing flickers or shows twice.
 */
export function useChatSession(input: {
  conversationId: string;
  messages: MessageRow[];
  about: { kind: AboutKind; id: string } | null;
}): { pending: PendingQuestion | null; send: (text: string, webSearch: boolean) => void } {
  const { sessionKey } = useSession();
  const [pending, setPending] = useState<PendingQuestion | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  // Hand over to the pulled rows once they hold what the overlay shows.
  useEffect(() => {
    if (!pending) return;
    const hasQuestion = input.messages.some((message) => message.id === pending.userMessageId);
    const hasAnswer = pending.live.messageId !== null && input.messages.some((m) => m.id === pending.live.messageId);
    if (hasQuestion && (hasAnswer || pending.live.failed)) setPending(null);
  }, [input.messages, pending]);

  const send = useCallback(
    (text: string, webSearch: boolean) => {
      const question = text.trim();
      // A failed question may be sent again (Try again); one still answering may not.
      if (!question || !sessionKey || (pending && !pending.live.failed)) return;

      const userMessageId = randomUUID();
      const update = (change: (live: LiveAnswer) => LiveAnswer) =>
        setPending((current) => (current && current.userMessageId === userMessageId ? { ...current, live: change(current.live) } : current));
      setPending({ userMessageId, text: question, webSearch, live: EMPTY_LIVE });
      controller.current = new AbortController();

      streamAnswer({
        conversationId: input.conversationId,
        // The server reads `about` only when this question creates the chat.
        body: { user_message_id: userMessageId, text: question, web_search: webSearch, about: input.messages.length === 0 ? input.about : null },
        sessionKey,
        signal: controller.current.signal,
        onEvent: (event) => update((live) => applyEvent(live, event)),
      })
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
