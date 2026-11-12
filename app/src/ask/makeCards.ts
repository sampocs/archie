/**
 * The one answer that offers Make cards: the chat's last turn, when it is a finished answer without its own card set.
 * Make cards always reads the whole chat, so one button at the end does what a button under every answer would. A chat
 * about a review card never offers it (it is there to change that card), nor does one with a question in flight.
 */
export function makeCardsAnswerId(input: {
  turns: { id: string; role: string; status: string }[];
  hasCardSet: (messageId: string) => boolean;
  aboutKind: string | null;
  questionInFlight: boolean;
}): string | null {
  const last = input.turns.at(-1);
  if (input.aboutKind === "card" || input.questionInFlight || !last) return null;
  if (last.role !== "assistant" || last.status !== "complete" || input.hasCardSet(last.id)) return null;
  return last.id;
}
