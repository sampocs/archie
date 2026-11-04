import type { ChosenTopic } from "@/db/actions";

import type { DomainName } from "./domains";
import { MAX_TOPIC_NAME_LENGTH, normalizeTopicName } from "./topicName";

/** Adds `topic` to the picks, or removes it when it is already picked. */
export function togglePick(picked: ChosenTopic[], topic: ChosenTopic): ChosenTopic[] {
  const isPicked = picked.some((pick) => isSameTopic(pick, topic));
  return isPicked ? picked.filter((pick) => !isSameTopic(pick, topic)) : [...picked, topic];
}

/** Adds a topic the user typed in, or says why it can't be (empty, too long, or already picked). */
export function addOwn(
  picked: ChosenTopic[],
  domain: DomainName,
  name: string,
): { picked: ChosenTopic[]; error: string | null } {
  const cleaned = name.split(/\s+/).filter(Boolean).join(" ");
  if (!cleaned) return { picked, error: "Give the topic a name." };
  if (cleaned.length > MAX_TOPIC_NAME_LENGTH) {
    return { picked, error: `Keep it under ${MAX_TOPIC_NAME_LENGTH} characters.` };
  }

  // Names are unique per user across domains, so the check ignores the domain.
  const wanted = normalizeTopicName(cleaned);
  if (picked.some((pick) => normalizeTopicName(pick.name) === wanted)) return { picked, error: "Already picked." };

  return { picked: [...picked, { domain, name: cleaned, origin: "user" }], error: null };
}

function isSameTopic(left: ChosenTopic, right: ChosenTopic): boolean {
  return left.domain === right.domain && normalizeTopicName(left.name) === normalizeTopicName(right.name);
}
