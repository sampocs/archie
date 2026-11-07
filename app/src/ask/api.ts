import { apiFetch } from "@/api/client";

export type CardDraft = { question: string; answer: string };

/** Haiku's draft of one card from an answer. */
export async function fetchCardDraft(messageId: string, sessionKey: string): Promise<CardDraft> {
  const body = (await apiFetch(`/ask/messages/${messageId}/card-draft`, { method: "POST", sessionKey })) as CardDraft;
  return { question: String(body.question ?? ""), answer: String(body.answer ?? "") };
}

/** Saves the owner's card; it reaches Review through the next pull. */
export async function saveCard(input: { messageId: string; question: string; answer: string; sessionKey: string }) {
  await apiFetch("/ask/cards", {
    method: "POST",
    sessionKey: input.sessionKey,
    body: { message_id: input.messageId, question: input.question.trim(), answer: input.answer.trim() },
  });
}
