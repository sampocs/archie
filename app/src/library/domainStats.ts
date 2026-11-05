import { DOMAINS, type DomainName } from "@/topics/domains";

import { isLiveTopic, type LibraryData, type TopicRow } from "./join";

// `unreadPrimer`: the topic's current primer exists and nobody has opened it.
export type DomainChip = { topic: TopicRow; count: number; own: boolean; unreadPrimer: boolean };

export type DomainCard = {
  domain: DomainName;
  count: number;
  done: number;
  queued: number;
  inbox: number;
  chips: DomainChip[];
};

/** One card per domain with items or user-added live topics, biggest first, ties in `DOMAINS` order. */
export function domainCards(data: LibraryData): DomainCard[] {
  const liveTopics = data.topics.filter(isLiveTopic);
  const unreadPrimerTopics = new Set(
    data.topicPrimers.filter((primer) => primer.isCurrent === 1 && !primer.openedAt).map((primer) => primer.topicId),
  );
  const topicCounts = new Map<string, number>();
  for (const source of data.sources) {
    if (source.topicId) topicCounts.set(source.topicId, (topicCounts.get(source.topicId) ?? 0) + 1);
  }

  const cards = DOMAINS.map((domain): DomainCard => {
    const sources = data.sources.filter((source) => source.domain === domain);
    const done = sources.filter((source) => source.state === "consumed").length;
    const queued = sources.filter((source) => source.state === "queued").length;
    const topics = liveTopics.filter((topic) => topic.domain === domain);

    const withItems = topics
      .filter((topic) => (topicCounts.get(topic.id) ?? 0) > 0)
      .map((topic) => ({
        topic,
        count: topicCounts.get(topic.id) ?? 0,
        own: false,
        unreadPrimer: unreadPrimerTopics.has(topic.id),
      }))
      .sort((a, b) => b.count - a.count || a.topic.name.localeCompare(b.topic.name));
    const ownEmpty = topics
      .filter((topic) => topic.origin === "user" && !topicCounts.has(topic.id))
      .map((topic) => ({ topic, count: 0, own: true, unreadPrimer: unreadPrimerTopics.has(topic.id) }))
      .sort((a, b) => a.topic.name.localeCompare(b.topic.name));

    return {
      domain,
      count: sources.length,
      done,
      queued,
      inbox: sources.length - done - queued,
      chips: [...withItems, ...ownEmpty],
    };
  });

  // Array.sort is stable, so equal counts keep DOMAINS order.
  return cards.filter((card) => card.count > 0 || card.chips.length > 0).sort((a, b) => b.count - a.count);
}
