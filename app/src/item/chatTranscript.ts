import { groupSections } from "@/ask/sections";
import { parseSegments } from "@/ask/types";

type TranscriptMessage = { role: string; text: string; segments: string | null; status: string };

const COMPLETE = "complete";
const ASSISTANT = "assistant";

/**
 * A chat as read-only markdown, `**You:** …` / `**Archie:** …` turn by turn, as the server writes a chat item's text.
 * The phone builds it from the chat's synced messages when it can't fetch the saved one; unfinished answers are left
 * out, and an answer reads as its sections' text.
 */
export function transcriptMarkdown(messages: TranscriptMessage[]): string {
  return messages
    .filter((message) => message.role !== ASSISTANT || message.status === COMPLETE)
    .map((message) => {
      if (message.role !== ASSISTANT) return `**You:** ${message.text.trim()}`;
      const sections = groupSections(parseSegments(message.segments));
      const answer = sections.length > 0 ? sections.map((section) => section.text).join("\n\n") : message.text.trim();
      return `**Archie:** ${answer}`;
    })
    .join("\n\n");
}
