import type { Section } from "./sections";

/** The nav bar's back label: the note's title when the chat opened from that note's page, otherwise "Ask". */
export function backLabelOf(fromNote: string | undefined, aboutTitle: string | null): string {
  return fromNote && aboutTitle ? aboutTitle : "Ask";
}

/**
 * Whether a section shows its kicker. An answer that carries proposals (quiet labels) drops the "Background" label
 * from an uncited section, so the proposal under it isn't framed by a label that says nothing.
 */
export function showsSectionLabel(section: Pick<Section, "label" | "citations">, quietLabels: boolean): boolean {
  return !(quietLabels && section.label === "background" && section.citations.length === 0);
}
