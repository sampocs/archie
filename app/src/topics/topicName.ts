import type { TopicRow } from "@/library/join";

export const MAX_TOPIC_NAME_LENGTH = 80;

/** The form names are compared in, matching the server's `normalize_topic_name`. */
export function normalizeTopicName(name: string): string {
  return name.toLowerCase().replace(/&/g, " and ").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

/** A testID-safe form of a domain or topic name: "Fed & monetary policy" → "fed-monetary-policy". */
export function slugify(text: string): string {
  return text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "");
}

/** Why `name` can't be used for a new or renamed topic, or null; mirrors the server's checks. */
export function topicNameError(name: string, topics: TopicRow[], ignoreId?: string): string | null {
  const cleaned = name.split(/\s+/).filter(Boolean).join(" ");
  if (!cleaned) return "Give the topic a name.";
  if (cleaned.length > MAX_TOPIC_NAME_LENGTH) return `Keep it under ${MAX_TOPIC_NAME_LENGTH} characters.`;

  const wanted = normalizeTopicName(cleaned);
  const clash = topics.find(
    (topic) => topic.id !== ignoreId && !topic.mergedIntoId && normalizeTopicName(topic.name) === wanted,
  );
  if (!clash) return null;
  return clash.removedAt ? "You removed a topic with this name. Restore it in Settings." : "You already have this topic.";
}
