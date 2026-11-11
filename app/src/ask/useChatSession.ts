import { randomUUID } from "expo-crypto";
import { useCallback, useEffect, useRef, useState } from "react";

import { UnauthorizedError } from "@/api/client";
import { clearSession, useSession } from "@/auth/session";
import { requestSync } from "@/sync/useSync";

import type { CardSetChoice } from "./cardSets";
import {
  ANSWER_WAIT_MS,
  applyEvent,
  EMPTY_LIVE,
  endOfStream,
  handedOver,
  type LiveAnswer,
  type PendingQuestion,
} from "./sections";
import { StreamCutError, streamAnswer } from "./stream";
import type { AboutKind, MessageRow } from "./types";

export type { PendingQuestion };

const POLL_MS = 5_000;

/**
 * Sending a question and showing its answer as it streams. The server finishes and saves the answer even if the phone
 * hangs up or the chat is left, and the next pull brings it. A stream that ends or breaks after the server took the
 * question leaves the overlay waiting ("Still answering…"): it syncs every 5 s and turns failed after `ANSWER_WAIT_MS`
 * with nothing pulled. A request that never opened, or an `error` event, fails at once. The overlay stays until the
 * pulled rows hold the question and its answer (or, for a failed or waiting stream, a later assistant row), and the
 * returned `pending` is already null on the render where they land, so nothing flickers or shows twice. A question
 * carries `cardSetChoice`, the open card set's Keep ticks as they stand when it is sent.
 */
export function useChatSession(input: {
  conversationId: string;
  messages: MessageRow[];
  about: { kind: AboutKind; id: string } | null;
  cardSetChoice: CardSetChoice | null;
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

  // While waiting on the server, pull every few seconds; give up on the answer after ANSWER_WAIT_MS.
  const waitingSince = overlay && overlay.live.waiting && !overlay.live.failed ? overlay.sentAt : null;
  const userMessageId = overlay?.userMessageId;
  useEffect(() => {
    if (waitingSince === null) return;
    const poll = setInterval(() => requestSync(), POLL_MS);
    const giveUp = setTimeout(
      () =>
        setOverlay((current) =>
          current && current.userMessageId === userMessageId
            ? { ...current, live: { ...current.live, waiting: false, failed: true } }
            : current,
        ),
      Math.max(0, waitingSince + ANSWER_WAIT_MS - Date.now()),
    );
    return () => {
      clearInterval(poll);
      clearTimeout(giveUp);
    };
  }, [waitingSince, userMessageId]);

  // Drop the overlay's state once the pulled rows have taken over (`pending` already hides it during that render).
  useEffect(() => {
    if (overlay && handedOver(overlay, input.messages)) setOverlay(null);
  }, [input.messages, overlay]);

  const send = useCallback(
    (text: string, webSearch: boolean) => {
      const question = text.trim();
      // A failed question may be sent again (Try again); one still answering or waiting may not.
      if (!question || !sessionKey || (pending && !pending.live.failed)) return;

      const userMessageId = randomUUID();
      const update = (change: (live: LiveAnswer) => LiveAnswer) => {
        if (!mounted.current) return;
        setOverlay((current) =>
          current && current.userMessageId === userMessageId ? { ...current, live: change(current.live) } : current,
        );
      };
      const choice = input.cardSetChoice;
      setOverlay({ userMessageId, text: question, webSearch, sentAt: Date.now(), cardSetChoice: choice, live: EMPTY_LIVE });

      streamAnswer({
        conversationId: input.conversationId,
        // The server reads `about` only when this question creates the chat.
        body: {
          user_message_id: userMessageId,
          text: question,
          web_search: webSearch,
          about: input.messages.length === 0 ? input.about : null,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          card_set_choice: choice && { proposal_id: choice.proposal_id, kept: choice.kept },
        },
        sessionKey,
        onEvent: (event) => update((live) => applyEvent(live, event)),
      })
        .then(() => update(endOfStream))
        .catch((error) => {
          if (error instanceof UnauthorizedError) void clearSession();
          // A body that broke after the server answered 200 means it holds the question: wait for its answer.
          if (error instanceof StreamCutError) return update(endOfStream);
          update((live) => ({ ...live, failed: true, searching: null, editing: false, draftingCards: false }));
        })
        .finally(() => requestSync());
    },
    [input.conversationId, input.messages.length, input.about, input.cardSetChoice, pending, sessionKey],
  );

  return { pending, send };
}
