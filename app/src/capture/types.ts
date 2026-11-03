export type Intent = "finished" | "queue";
export type Reaction = "easy" | "mostly" | "lost";
export type CaptureChoice = { intent: Intent | null; reaction: Reaction | null; note: string; prepMe: boolean };

export const EMPTY_CHOICE: CaptureChoice = { intent: null, reaction: null, note: "", prepMe: false };
