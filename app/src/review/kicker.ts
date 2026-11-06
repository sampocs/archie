import { asTakeKind, TAKE_KIND_DOMAIN, TAKE_KIND_LABELS } from "@/takes/takes";

import { cardDomain, cardOrigin, type ReviewData } from "./eligibility";
import { KIND_LABELS } from "./labels";
import type { CardRow } from "./types";

export type CardKickerParts = { label: string | undefined; suffix: string | undefined; domain: string | null };

/** The question card's kicker: "<Domain> · <Kind>", "This week · News" for quiz cards, "Your take · <kind>". */
export function cardKicker(card: CardRow, data: ReviewData): CardKickerParts {
  if (card.kind === "quiz") return { label: "This week", suffix: "News", domain: null };

  const origin = cardOrigin(card);
  if (origin.kind === "take") {
    // Takes have no domain; the kicker takes the kind's colour instead, as on the Takes list.
    const kind = asTakeKind(data.takesById.get(origin.takeId)?.kind ?? "talking_point");
    return { label: "Your take", suffix: TAKE_KIND_LABELS[kind], domain: TAKE_KIND_DOMAIN[kind] };
  }
  return { label: undefined, suffix: KIND_LABELS[card.kind], domain: cardDomain(card, data) };
}
