import { API_URL, ClientError, NetworkError, UnauthorizedError } from "@/api/client";

import type { AboutKind, AskEvent } from "./types";

export type AskBody = {
  user_message_id: string;
  text: string;
  web_search: boolean;
  about: { kind: AboutKind; id: string } | null;
  // The phone's IANA zone, so "today" and "on Tuesday" mean the owner's days.
  timezone: string;
  // The open card set's Keep ticks, when some card is unticked; the server ignores ticks that no longer fit the set.
  card_set_choice: { proposal_id: string; kept: number[] } | null;
};

const EVENT_TYPES = new Set(["delta", "block", "searching", "done", "error", "editing", "edit", "drafting_cards", "cards"]);

/** The body of an answer that was opened (the server answered 200) broke before it ended. */
export class StreamCutError extends Error {}

/** Server-sent events from text chunks that may split a frame anywhere. */
export class SseParser {
  private buffer = "";

  push(chunk: string): AskEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const frames = this.buffer.split("\n\n");
    this.buffer = frames.pop() ?? "";
    return frames.flatMap((frame) => {
      const event = parseFrame(frame);
      return event ? [event] : [];
    });
  }
}

function parseFrame(frame: string): AskEvent | null {
  let name = "";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trim());
  }
  if (!EVENT_TYPES.has(name)) return null;
  try {
    return { type: name, ...(JSON.parse(data.join("\n")) as object) } as AskEvent;
  } catch {
    return null;
  }
}

/**
 * Asks the question and calls `onEvent` for each event as it arrives. Expo's global fetch (`expo/fetch`) streams the
 * response body. Throws `UnauthorizedError`, `ClientError` (403/404/409/422) or `NetworkError` (offline, 5xx: the
 * request never opened, so the answer failed), or `StreamCutError` once the server answered 200 and the body then broke:
 * the server holds the question and finishes the answer anyway, so the caller waits for it instead of failing.
 */
export async function streamAnswer(input: {
  conversationId: string;
  body: AskBody;
  sessionKey: string;
  signal?: AbortSignal;
  onEvent: (event: AskEvent) => void;
}): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/ask/conversations/${input.conversationId}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${input.sessionKey}`,
      },
      body: JSON.stringify(input.body),
      signal: input.signal,
    });
  } catch (error) {
    throw new NetworkError(String(error));
  }
  if (response.status === 401) throw new UnauthorizedError("401 from ask");
  if (response.status >= 500) throw new NetworkError(`${response.status} from ask`);
  if (!response.ok) throw new ClientError(`${response.status} from ask`);

  const reader = response.body?.getReader();
  if (!reader) throw new NetworkError("ask answered without a stream");
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.push(decoder.decode(value, { stream: true })).forEach(input.onEvent);
    }
  } catch (error) {
    throw new StreamCutError(String(error));
  }
  parser.push(`${decoder.decode()}\n\n`).forEach(input.onEvent);
}
