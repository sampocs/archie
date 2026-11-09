import { asTakeKind, TAKE_KIND_DOMAIN, TAKE_KIND_LABELS } from "@/takes/takes";
import { CHAT_KIND, kindLabel } from "@/ui/sourceLabels";

import { cardDomain, cardOrigin, type ReviewData } from "./eligibility";
import { KIND_LABELS } from "./labels";
import type { CardRow } from "./types";

export type CardKickerParts = { label: string | undefined; suffix: string | undefined; domain: string | null };

/**
 * The question card's kicker: "<Domain> · <Kind>", "This week · News" for quiz cards, "Your take · <kind>", and
 * "From Ask" for chat cards, in the colour of what the chat was about.
 */
export function cardKicker(card: CardRow, data: ReviewData): CardKickerParts {
  if (card.kind === "quiz") return { label: "This week", suffix: "News", domain: null };

  const origin = cardOrigin(card);
  if (origin.kind === "take") {
    // Takes have no domain; the kicker takes the kind's colour instead, as on the Takes list.
    const kind = asTakeKind(data.takesById.get(origin.takeId)?.kind ?? "talking_point");
    return { label: "Your take", suffix: TAKE_KIND_LABELS[kind], domain: TAKE_KIND_DOMAIN[kind] };
  }
  if (origin.kind === "conversation") {
    return { label: "From Ask", suffix: undefined, domain: conversationDomain(origin.conversationId, data) };
  }
  return { label: undefined, suffix: KIND_LABELS[card.kind], domain: cardDomain(card, data) };
}

/** A chat item's card names its item instead of a kicker: `From {title} · Chat`, opening the item. */
export type ChatItemLine = { sourceId: string; title: string; kind: string };

/** The source line of a card from a chat item (the cheat sheet saved from an Ask chat); null for any other card. */
export function chatItemLine(card: CardRow, data: ReviewData): ChatItemLine | null {
  const origin = cardOrigin(card);
  if (origin.kind !== "source") return null;
  const source = data.sourcesById.get(origin.sourceId);
  if (!source || source.kind !== CHAT_KIND) return null;
  return { sourceId: source.id, title: source.title ?? kindLabel(CHAT_KIND), kind: kindLabel(CHAT_KIND) };
}

/** The domain colour of what a chat was about: a source's domain, a topic primer's topic's, a take kind's; else none. */
function conversationDomain(conversationId: string, data: ReviewData): string | null {
  const conversation = data.conversationsById.get(conversationId);
  if (!conversation) return null;
  if (conversation.aboutSourceId) return data.sourcesById.get(conversation.aboutSourceId)?.domain ?? null;
  if (conversation.aboutTopicPrimerId) {
    const primer = data.topicPrimersById.get(conversation.aboutTopicPrimerId);
    return primer ? (data.topicsById.get(primer.topicId)?.domain ?? null) : null;
  }
  if (conversation.aboutTakeId) {
    const take = data.takesById.get(conversation.aboutTakeId);
    return take ? TAKE_KIND_DOMAIN[asTakeKind(take.kind)] : null;
  }
  return null;
}
