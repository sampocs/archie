export type Intent = "finished" | "queue";
/** What a capture does: a library intent, or saving the link into a collection (never a source). */
export type Destination = Intent | "collection";
export type Reaction = "easy" | "mostly" | "lost";
export type CollectionPick = { kind: "existing"; id: string } | { kind: "new"; name: string };
export type CaptureChoice = {
  intent: Destination | null;
  reaction: Reaction | null;
  note: string;
  queuePrimer: boolean;
  collection: CollectionPick | null;
};

export const EMPTY_CHOICE: CaptureChoice = {
  intent: null,
  reaction: null,
  note: "",
  queuePrimer: false,
  collection: null,
};

/**
 * Switching intent drops the other intent's answers: the server rejects a reaction on a queued source, and a
 * collection save carries only its pick (`defaultPick` seeds it so Save reads what the picker shows).
 */
export function chooseIntent(
  choice: CaptureChoice,
  intent: Destination,
  defaultPick?: CollectionPick,
): CaptureChoice {
  if (intent === choice.intent) return choice;
  return { ...EMPTY_CHOICE, intent, collection: intent === "collection" ? (defaultPick ?? null) : null };
}
