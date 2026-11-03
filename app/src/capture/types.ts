export type Intent = "finished" | "queue";
export type Reaction = "easy" | "mostly" | "lost";
export type CaptureChoice = {
  intent: Intent | null;
  reaction: Reaction | null;
  note: string;
  prepMe: boolean;
};

export const EMPTY_CHOICE: CaptureChoice = {
  intent: null,
  reaction: null,
  note: "",
  prepMe: false,
};

/** Switching intent drops the other intent's answers: the server rejects a reaction on a queued source. */
export function chooseIntent(
  choice: CaptureChoice,
  intent: Intent,
): CaptureChoice {
  return intent === choice.intent ? choice : { ...EMPTY_CHOICE, intent };
}
